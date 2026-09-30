"""Разбор записи лекции: расшифровка, слайды и, по желанию, конспект сверху.

Всё считается локально: ffmpeg снимает звук, mlx-whisper распознаёт речь,
slides.py ищет слайды по картинке, mlx-lm пишет конспект. Слайды ищутся
параллельно с распознаванием: одно занято видеокартой, другое процессором.
"""
import re, subprocess, tempfile, threading, time
from pathlib import Path

from i18n import current as _lang, t, tf

HERE = Path(__file__).resolve().parent


def _tool(name):
    """Программа из бандла, затем из PATH, затем из обычных мест установки."""
    import shutil
    inside = HERE / "bin" / name
    if inside.exists():
        return str(inside)
    found = shutil.which(name)
    if found:
        return found
    for base in ("/opt/homebrew/bin", "/usr/local/bin"):
        if (Path(base) / name).exists():
            return str(Path(base) / name)
    return name


FFMPEG = _tool("ffmpeg")
AUDIO_ONLY = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}")
BATCH = 4                    # столько запросов модель обрабатывает за один проход


class Cancelled(Exception):
    """Нажата «Отмена»."""


_STOP = None


def _check():
    if _STOP is not None and _STOP():
        raise Cancelled()


def run(cmd):
    """Внешняя программа с оглядкой на отмену."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True)
    # communicate вместо poll: невычитанный канал в 64 КБ вешает процесс.
    while True:
        try:
            out, err = proc.communicate(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            if _STOP is not None and _STOP():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise Cancelled()
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def hhmmss(sec):
    sec = int(sec)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def base_name(path):
    """Имя для файлов: дата и время записи.

    OBS и большинство записывалок уже называют файл так — берём как есть.
    Иначе — время создания файла: у записи экрана это начало лекции.
    """
    found = STAMP.search(Path(path).stem)
    if found:
        return found.group(0)
    st = Path(path).stat()
    made = getattr(st, "st_birthtime", st.st_mtime)
    return time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(made))


MONTHS = {"ru": ("января февраля марта апреля мая июня июля августа сентября "
                 "октября ноября декабря").split(),
          "en": ("January February March April May June July August September "
                 "October November December").split()}


def human_stamp(base):
    """«30 сентября 2026, 09:05» из «2026-09-30_09-05-51»."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})", base)
    if not m:
        return base
    y, mo, d, hh, mm = m.groups()
    month = MONTHS["en" if _lang() == "en" else "ru"][int(mo) - 1]
    return f"{int(d)} {month} {y}, {hh}:{mm}"


# ---------------------------------------------------------------- речь

ASR_PROMPT = ("Расшифровка разговора со знаками препинания, заглавными буквами "
              "и абзацами.")

# Замерено: знаки препинания держатся на 89/95/93% длины при 300/240/180 с.
ASR_PIECE = 240.0
ASR_MODEL = "mlx-community/whisper-large-v3-mlx"


def _quiet_cut(audio, sr, target, window=4.0):
    """Разрез в самом тихом месте рядом с целью: ровно по времени рвёт слово."""
    import numpy as np
    lo = max(0, int((target - window) * sr))
    hi = min(len(audio), int((target + window) * sr))
    if hi - lo < int(0.4 * sr):
        return min(int(target * sr), len(audio))
    step = int(0.05 * sr)
    part = np.abs(audio[lo:hi])
    best, best_at = None, lo
    for i in range(0, len(part) - step, step):
        lvl = float(part[i:i + step].mean())
        if best is None or lvl < best:
            best, best_at = lvl, lo + i
    return best_at


def _echo(text, prompt):
    """Модель повторила нашу подсказку вместо речи.

    В конце записи, на тишине, она дописывает начальную подсказку как реплику:
    «Заглавные буквами и абзацами». Уверенность при этом высокая, по тишине
    такое не отсеять.
    """
    root = lambda w: w[:5]
    ours = {root(w) for w in re.findall(r"\w+", prompt.lower()) if len(w) > 3}
    words = [root(w) for w in re.findall(r"\w+", text.lower()) if len(w) > 3]
    return bool(words) and sum(w in ours for w in words) >= len(words) * 0.8


def local_first(repo):
    """Скачанную модель берём с диска, не спрашивая Hugging Face.

    По имени mlx-lm и mlx-whisper каждый раз сверяют версию с сервером: с
    ответом это полсекунды, без ответа загрузка стоит."""
    try:
        import models_home
        found = models_home.resolve(repo)
        if found is not None:
            return str(found)     # общее хранилище: своя папка или общий кэш
    except Exception:
        pass
    try:
        from huggingface_hub import snapshot_download
        return snapshot_download(repo, local_files_only=True)
    except Exception:
        return repo


def free_memory():
    """Отпустить веса моделей и вернуть память системе.

    Whisper держит свою модель в классовой переменной библиотеки, MLX — пул
    освобождённых буферов. Пока их не тронуть, простаивающее приложение
    занимает столько же, сколько во время работы.
    """
    try:
        import gc, importlib
        import mlx.core as mx
        # Именно модуль, а не одноимённая функция из mlx_whisper.
        holder = importlib.import_module("mlx_whisper.transcribe").ModelHolder
        holder.model = None
        holder.model_path = None
        gc.collect()
        mx.clear_cache()
    except Exception:
        pass


def _looped(segs, times=6):
    """Расшифровка сорвалась в повтор одной и той же фразы.

    На однообразной речи — перекличке, списке фамилий — модель может
    зацепиться за фразу и писать её до конца куска.
    """
    if len(segs) < times * 2:
        return False
    count = {}
    for s in segs:
        key = " ".join(s["text"].lower().split())
        count[key] = count.get(key, 0) + 1
    most = max(count.values())
    return most >= times and most > len(segs) * 0.5


def _copied(text, hint):
    """Реплика — дословный кусок подсказки: на неразборчивом звуке модель
    переписывает её вместо речи. Совпадение отдельных слов не в счёт — лектор
    и должен произносить термины со слайда."""
    norm = lambda x: " ".join(re.findall(r"\w+", x.lower()))
    txt = norm(text)
    return len(txt) > 15 and txt in norm(hint)


def transcribe(wav, log=lambda m: None, step=lambda n, total: None,
               hint_for=lambda a, b: ""):
    """Распознавание кусками по четыре минуты, каждый со своей подсказкой.

    Без подсказки модель выдаёт поток строчными без знаков препинания, а одной
    на файл мало: через три-четыре минуты знаки пропадают. Прошлый вывод модели
    ей на вход не подаём — именно он уводит её в повтор одной фразы.

    hint_for(начало, конец) даёт термины со слайдов, показанных в этом куске:
    с ними модель реже искажает фамилии и специальные слова.
    """
    import mlx_whisper, soundfile as sf

    audio, sr = sf.read(str(wav), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    cuts, at = [0], 0
    while len(audio) - at > ASR_PIECE * sr * 1.5:
        at = _quiet_cut(audio, sr, at / sr + ASR_PIECE)
        cuts.append(at)
    cuts.append(len(audio))
    total = len(cuts) - 1

    asr = local_first(ASR_MODEL)
    segs, langs = [], []
    for n, (a, b) in enumerate(zip(cuts, cuts[1:]), 1):
        _check()
        step(n - 1, total)
        hint = hint_for(a / sr, b / sr)
        # Подсказка — впереди: модель обрезает длинную с начала, а указание
        # про знаки препинания терять нельзя.
        prompt = (hint + " " if hint else "") + ASR_PROMPT
        r = mlx_whisper.transcribe(audio[a:b], path_or_hf_repo=asr,
                                   verbose=False, initial_prompt=prompt,
                                   condition_on_previous_text=False)
        # На жадном декодировании повтор воспроизводится слово в слово,
        # поэтому переспрашиваем с температурой.
        if _looped(r["segments"]):
            log(t("  кусок сорвался в повтор, распознаётся заново"))
            r = mlx_whisper.transcribe(
                audio[a:b], path_or_hf_repo=asr, verbose=False,
                initial_prompt=prompt, condition_on_previous_text=False,
                temperature=(0.4, 0.6, 0.8, 1.0))
        came = len(segs)
        langs.append(r.get("language", ""))
        off = a / sr
        for s in r["segments"]:
            txt = s["text"].strip()
            if not txt or s["end"] - s["start"] < 0.2:
                continue
            # Речь за краем куска модель дорисовывает: там уже нет звука.
            if s["start"] >= (b - a) / sr - 0.5:
                continue
            # Выдумки на тишине: у живой речи «тишина» не выше 0.06,
            # у выдумок — от 0.74.
            if s.get("no_speech_prob", 0) > 0.5:
                continue
            # «hai hai hai…»: у связной речи сжатие не выше 2.1.
            if s.get("compression_ratio", 0) > 2.4:
                continue
            if _echo(txt, ASR_PROMPT) or (hint and _copied(txt, hint)):
                continue
            if segs and segs[-1]["text"] == txt:
                continue
            segs.append({"start": s["start"] + off, "end": s["end"] + off,
                         "text": txt})
        if _looped(segs[came:]):
            log(t("  повтор остался, из куска берётся по реплике"))
            seen, clean = set(), []
            for s in segs[came:]:
                key = " ".join(s["text"].lower().split())
                if key not in seen:
                    seen.add(key)
                    clean.append(s)
            segs[came:] = clean
    step(total, total)
    # Язык — какой чаще: на тишине в конце модель опознаёт что попало.
    count = {}
    for code in langs:
        if code:
            count[code] = count.get(code, 0) + 1
    free_memory()
    return segs, (max(count, key=count.get) if count else "ru")


# ---------------------------------------------------------------- конспект

MODEL_ID = "mlx-community/Qwen3.6-35B-A3B-4bit"
CHUNK_SECONDS = 600


def OUT():
    """Требование языка ответа; сами указания остаются русскими."""
    return "IN ENGLISH" if _lang() == "en" else "ПО-РУССКИ"


HEADS = {
    "Кратко": "Summary", "Темы": "Topics", "Подробнее": "In detail",
    "Определения и формулы": "Definitions and formulas",
    "Задания": "Assignments", "Расшифровка": "Transcript",
    "Лекция": "Lecture", "Слайд": "Slide", "этап": "stage",
}


def h(name):
    return HEADS[name] if _lang() == "en" and name in HEADS else name


def chunk(segs, seconds=CHUNK_SECONDS):
    """Нарезка по времени: на длинном тексте модель хуже помнит начало."""
    out, cur, base = [], [], segs[0]["start"] if segs else 0
    for s in segs:
        if s["start"] - base > seconds and cur:
            out.append({"start": base, "text": " ".join(x["text"] for x in cur)})
            cur, base = [], s["start"]
        cur.append(s)
    if cur:
        out.append({"start": base, "text": " ".join(x["text"] for x in cur)})
    return out


# LaTeX в окне не рисуется, а с пробелами внутри «$ … $» — и в редакторах
# заметок: модель ставит их почти всегда.
FORMULAS = ("Формулы пиши обычным текстом с символами Юникода — a₁₁, Aᵢⱼ, "
            "(−1)ⁱ⁺ʲ, ·, ≠, ≤, ⇒, Σ — без LaTeX и без знаков $. ")


class Summarizer:
    def __init__(self, model_id=MODEL_ID):
        from mlx_lm import load
        from mlx_lm.sample_utils import make_sampler
        self.model, self.tok = load(local_first(model_id))
        self.sampler = make_sampler(temp=0.3, top_p=0.9)

    def _prompt(self, text, tokens=False):
        return self.tok.apply_chat_template([{"role": "user", "content": text}],
                                            add_generation_prompt=True,
                                            enable_thinking=False,
                                            tokenize=tokens)

    @staticmethod
    def _clean(text):
        return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()

    def _gen(self, prompt, max_tokens=1200):
        from mlx_lm import generate
        r = generate(self.model, self.tok, prompt=self._prompt(prompt),
                     max_tokens=max_tokens, sampler=self.sampler, verbose=False)
        return self._clean(r)

    def _gen_many(self, prompts, max_tokens=1200):
        """Партия запросов за один проход: генерация упирается в память,
        а не в счёт, и четыре ответа идут почти за время одного."""
        from mlx_lm import batch_generate
        out = []
        for i in range(0, len(prompts), BATCH):
            _check()
            group = prompts[i:i + BATCH]
            if len(group) == 1:
                out.append(self._gen(group[0], max_tokens))
                continue
            r = batch_generate(self.model, self.tok,
                               [self._prompt(x, tokens=True) for x in group],
                               max_tokens=max_tokens, sampler=self.sampler)
            out += [self._clean(x) for x in r.texts]
        return out

    def notes(self, parts):
        total = len(parts)
        return self._gen_many([
            f"Ниже кусок расшифровки лекции ({i} из {total}), начало в "
            f"{hhmmss(p['start'])}. Расшифровка автоматическая: термины и "
            "фамилии могут быть искажены, восстанавливай их по смыслу.\n"
            f"Изложи {OUT()}, что в этом куске объяснялось: понятия и "
            "определения, утверждения и правила, формулы (словами или в "
            "обычной записи), разобранные примеры и задачи с ходом решения. "
            "Организационное — задания, сроки, что будет на контрольной — "
            "отдельной строкой, если оно было. " + FORMULAS + "Только то, что "
            "есть в тексте, ничего не придумывай. Без вступлений.\n\n"
            + p["text"][:12000]
            for i, p in enumerate(parts, 1)])

    def reduce(self, notes, group=6):
        """Сводим разборы, пока они не поместятся в один запрос."""
        while len(notes) > group:
            groups = [notes[i:i + group] for i in range(0, len(notes), group)]
            notes = self._gen_many([
                f"Ниже разборы подряд идущих частей лекции. Сведи их {OUT()} "
                "в связный текст, сохранив все определения, формулы, примеры "
                "и организационные сведения. Без вступлений.\n\n"
                + "\n\n".join(g)[:14000] for g in groups], max_tokens=1600)
        return notes

    def overall(self, notes):
        return self._gen(
            "Ниже разбор лекции по порядку.\n"
            f"Составь {OUT()} учебный конспект. Строго такая разметка "
            "Markdown, без лишних заголовков:\n"
            f"## {h('Кратко')}\n3-5 предложений: тема лекции и что на ней "
            "разобрали.\n\n"
            f"## {h('Темы')}\nОт 3 до 8 пунктов списком, в порядке лекции.\n\n"
            f"## {h('Подробнее')}\nПо подзаголовку `### ` на каждую тему из "
            "списка выше. Под каждым — определения, свойства, ход рассуждения "
            "и разобранные примеры связным текстом.\n\n"
            f"## {h('Определения и формулы')}\nСписком, каждая строка с «- »: "
            "термин или формула — что это значит. Только прозвучавшее.\n\n"
            f"## {h('Задания')}\nДомашние задания, сроки, что к следующему "
            "занятию. Если ничего такого не звучало — этот раздел не пиши "
            "вовсе.\n\n"
            + FORMULAS +
            "Ничего не выдумывай сверх текста. Без вступлений и "
            "пояснений.\n\n" + "\n\n".join(notes)[:16000],
            max_tokens=3000)


def summarize(segs, model_id, log=lambda m: None, step=lambda n, total: None):
    total_min = (segs[-1]["end"] - segs[0]["start"]) / 60
    # На длинной записи куски крупнее: иначе разбор дольше, чем даёт точности.
    seconds = CHUNK_SECONDS if total_min < 60 else 900 if total_min < 120 else 1200
    parts = chunk(segs, seconds)
    s = Summarizer(model_id)
    notes = []
    for i in range(0, len(parts), BATCH):
        _check()
        step(i, len(parts) + 1)
        notes += s.notes(parts[i:i + BATCH])
    step(len(parts), len(parts) + 1)
    _check()
    md = s.overall(s.reduce(notes))
    del s
    free_memory()
    return md


# ---------------------------------------------------------------- файлы

PAUSE_SECONDS = 4.0
BLOCK_SECONDS = 45


def transcript_blocks(segs, breaks=()):
    """Расшифровка абзацами: реплики Whisper — обрывки по нескольку секунд.

    Абзац рвётся на долгой паузе, раз в три четверти минуты и там, где
    появился новый слайд, — чтобы отметка слайда встала в своё место текста.
    """
    breaks = sorted(breaks)
    out, cur, base, prev_end, bi = [], [], None, None, 0
    for s in segs:
        crossed = False
        while bi < len(breaks) and breaks[bi] <= s["start"]:
            crossed, bi = True, bi + 1
        long_pause = prev_end is not None and s["start"] - prev_end >= PAUSE_SECONDS
        if cur and (crossed or long_pause or s["start"] - base > BLOCK_SECONDS):
            out.append((base, " ".join(cur)))
            cur, base = [], None
        if base is None:
            base = s["start"]
        cur.append(s["text"])
        prev_end = s["end"]
    if cur:
        out.append((base, " ".join(cur)))
    return out


def _md_safe(line):
    """Распознанную строку — как простой текст. Иначе «=» под строкой делает
    из всей цитаты огромный заголовок, «1.» — список, а «*» — курсив."""
    line = re.sub(r"([\\`*_\[\]<>#|])", r"\\\1", line)
    line = re.sub(r"^(\d+)([.)])(\s)", r"\1\\\2\3", line)
    return re.sub(r"^([-+=])", r"\\\1", line)


def build_markdown(base, segs, summary="", slides=(), slides_dir=None, title=""):
    out = [f"# {title or h('Лекция')} · {human_stamp(base)}", ""]
    if summary:
        out += [summary.strip(), "", f"## {h('Расшифровка')}", ""]
    marks = sorted(slides, key=lambda x: x["start"])
    blocks = transcript_blocks(segs, [m["start"] for m in marks])
    mi = 0

    def slide_lines(m):
        rel = f"{slides_dir.name}/{m['file']}" if slides_dir else m["file"]
        name = f"{h('Слайд')} {m['n']}" + (
            f", {h('этап')} {m['stage']}" if m.get("stage") else "")
        lines = [f"**{hhmmss(m['start'])}** · {name}", "",
                 f"![{name}](<{rel}>)", ""]
        # Текст слайда цитатой: его прочтёт и тот, кто картинки не смотрит.
        if m.get("text"):
            lines += ["> " + _md_safe(x) for x in m["text"]] + [""]
        return lines

    for start, text in blocks:
        while mi < len(marks) and marks[mi]["start"] <= start:
            out += slide_lines(marks[mi]); mi += 1
        out += [f"**{hhmmss(start)}**", "", text, ""]
    while mi < len(marks):
        out += slide_lines(marks[mi]); mi += 1
    if not segs:
        out += [t("Речи в записи нет."), ""]
    return "\n".join(out)


def clean_title(text):
    """Название — часть имени файла: без знаков, которые файлы не терпят."""
    text = re.sub(r'[/\\:*?"<>|]', " ", text or "")
    return " ".join(text.split())[:60]


def process(source, out_dir, *, title="", own_folder=True, with_slides=True,
            with_summary=False, model_id=None, log=print,
            stage=lambda name, cur, total: None, should_stop=lambda: False):
    """Разобрать запись и сохранить результат в out_dir.

    Возвращает пути к файлам и текст расшифровки.
    """
    global _STOP
    _STOP = should_stop
    source = Path(source)
    out_dir = Path(out_dir)
    base = base_name(source)
    title = clean_title(title)
    tail = f" {title}" if title else ""
    # Всё по одной записи — в одной папке: название, а без него имя файла
    # записи, если это не та же дата; дата — в конце.
    name = title or clean_title(STAMP.sub("", source.stem).strip(" _-—"))
    # С предустановкой папка уже своя, на предмет: файлы ложатся прямо в неё.
    folder = (out_dir / (f"{name} — {base}" if name else base)) if own_folder else out_dir
    folder.mkdir(parents=True, exist_ok=True)
    md_path = folder / f"{t('Расшифровка')}{tail} — {base}.md"
    slides_dir = folder / f"{t('Слайды')}{tail} — {base}"
    video = source.suffix.lower() not in AUDIO_ONLY
    tmp = Path(tempfile.mkdtemp(prefix="lectures_"))

    # Слайды — в своём потоке, пока видеокарта занята распознаванием.
    found = {"saved": [], "error": None, "share": 0.0}

    def hint_for(a, b):
        """Термины со слайдов, что были на экране между a и b секундами."""
        words, seen = [], set()
        for s in list(found["saved"]):
            if s.get("text") and s["start"] <= b and s["end"] >= a:
                for w in re.findall(r"[^\W\d_]{4,}", " ".join(s["text"])):
                    if w.lower() not in seen:
                        seen.add(w.lower())
                        words.append(w)
        return " ".join(words)[:300].rsplit(" ", 1)[0] if words else ""

    def find_slides():
        import slides
        try:
            sheets, size, small_h, box = slides.find(
                source, FFMPEG, should_stop,
                lambda f: found.__setitem__("share", 0.8 * f))
            if not sheets:
                return
            slides_dir.mkdir(parents=True, exist_ok=True)
            # Старые картинки этой же записи — от прошлого разбора.
            for old in slides_dir.glob(f"* — {base}.png"):
                old.unlink()
            found["saved"] = slides.save(
                source, sheets, size, small_h, box, slides_dir, base, FFMPEG,
                should_stop, lambda f: found.__setitem__("share", 0.8 + 0.2 * f),
                label=t("Слайд"), tail=tail)
            import slide_text
            for s in found["saved"]:
                if should_stop():
                    return
                if s.get("stage"):
                    continue          # этап — часть готового слайда, текст у того
                try:
                    s["text"] = slide_text.read(slides_dir / s["file"])
                except Exception:
                    s["text"] = []
        except InterruptedError:
            pass
        except Exception as e:
            found["error"] = e

    worker = None
    try:
        if with_slides and video:
            log(t("Поиск слайдов…"))
            worker = threading.Thread(target=find_slides, daemon=True)
            worker.start()

        stage(t("Извлечение звука"), 0, 1)
        wav = tmp / "audio.wav"
        r = run([FFMPEG, "-y", "-v", "error", "-i", str(source), "-vn",
                 "-ac", "1", "-ar", "16000", str(wav)])
        segs = []
        if r.returncode == 0 and wav.exists() and wav.stat().st_size > 8000:
            stage(t("Распознавание речи"), 0, 1)
            log(t("Распознавание речи…"))
            segs, _ = transcribe(
                wav, log, lambda n, total: stage(t("Распознавание речи"), n, total),
                hint_for)
            log(tf("  реплик: {n}", n=len(segs)))
        else:
            log(t("  звуковой дорожки нет"))

        if worker is not None:
            while worker.is_alive():
                _check()
                stage(t("Поиск слайдов"), int(found["share"] * 100), 100)
                worker.join(0.3)
            _check()
            if found["error"]:
                log(tf("  слайды не получились: {e}", e=found["error"]))
            else:
                log(tf("  слайдов: {n}", n=len(found["saved"])))

        pdf_path = md_path.with_suffix(".pdf")

        def write_out(summary=""):
            md = build_markdown(base, segs, summary, found["saved"],
                                slides_dir if found["saved"] else None, title)
            md_path.write_text(md, encoding="utf-8")
            log(t("Сохранено: ") + md_path.name)
            if found["saved"]:
                # Один файл, чтобы отдать нейросети: расшифровка со слайдами.
                stage(t("Сборка PDF"), 0, 1)
                try:
                    import handout
                    handout.make_pdf(md, folder, pdf_path)
                    log(t("Сохранено: ") + pdf_path.name)
                except Exception as e:
                    log(tf("  PDF не получился: {e}", e=e))
            return md

        # Расшифровку — на диск сразу: конспект идёт долго, и если его прервать,
        # готовое распознавание не должно пропасть вместе с ним.
        md = write_out()
        if with_summary and sum(len(s["text"]) for s in segs) > 200:
            stage(t("Конспект"), 0, 1)
            log(t("Конспект…"))
            try:
                summary = summarize(segs, model_id or MODEL_ID, log,
                                    lambda n, total: stage(t("Конспект"), n, total))
                md = write_out(summary)
            except Cancelled:
                raise
            except Exception as e:
                # Расшифровка уже на диске; без конспекта разбор всё равно полезен.
                # Чаще всего это нехватка памяти, если рядом открыта другая модель.
                free_memory()
                log(tf("  конспект не получился: {e}", e=str(e)[:200]))
        return {"markdown": md, "md_path": str(md_path),
                "pdf_path": str(pdf_path) if found["saved"] and pdf_path.exists() else "",
                "slides_dir": str(slides_dir) if found["saved"] else "",
                "slides": [str(slides_dir / s["file"]) for s in found["saved"]],
                "segments": len(segs), "base": base}
    except Cancelled:
        if worker is not None:
            worker.join()             # поток сам видит отмену и выходит
        raise
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
        _STOP = None
