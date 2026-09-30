"""Слайды из записи лекции — без нейросети, по одному проходу.

Кадр в секунду, уменьшенный и серый, разбивается на клетки. Для каждой клетки
считается, как часто она меняется. Вебка, чат и прочие живые окна меняются
почти всегда — их клетки выпадают из рассмотрения. Остальное меняется, только
когда лектор листает, пишет пером или переключает слайд.

Слайд — это спокойный отрезок: несколько секунд подряд экран без изменений.
Из каждого такого отрезка берётся последний кадр — к этому моменту дописано
всё, что лектор успел. Дальше кадр сравнивается с предыдущим: тот же — пропуск,
дописан пером поверх прежнего — замена, иначе — новая остановка.

По тому, какие клетки менялись от остановки к остановке, находится область
содержимого: вебка, логотип, панель задач вокруг неё обрезаются. Остановки,
связанные прокруткой, склеиваются в одну длинную страницу, а неподвижные
панели по её краям срезаются — иначе они повторялись бы на каждом шаге.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

W = 384                  # ширина кадра для разбора
CELL = 16                # сторона клетки в точках разбора
STILL = 2.0              # клетка «не менялась», если средняя разница меньше
LIVE = 0.5               # клетка живая, если меняется чаще половины времени
CALM = 0.98              # кадр спокоен, если не менялись 98% неживых клеток
MIN_CALM = 3             # столько секунд спокойствия нужно слайду
SAME = 0.02              # слайды одинаковы, если различаются меньше 2% клеток
DIFF = 6.0               # клетка «другая» между слайдами — порог выше шума
FLAT = 4.0               # клетка «пустая», если разброс яркости меньше
INK = 5                  # столько клеток дописано — уже отдельный этап слайда


@dataclass
class Slide:
    start: float                 # когда появился
    end: float                   # когда был в последний раз спокоен
    frame: np.ndarray            # уменьшенный кадр — для сравнений
    live: np.ndarray             # живые клетки в этот момент
    since: float = -1.0          # с какого момента он именно такой, с пометками
    stages: list = field(default_factory=list)   # (с, по, кадр) до дописанного

    def __post_init__(self):
        if self.since < 0:
            self.since = self.start


def _probe(ffmpeg):
    """ffprobe лежит рядом с ffmpeg: в бандле свой, в системе общий."""
    near = Path(ffmpeg).with_name("ffprobe")
    return str(near) if near.parent != Path(".") and near.exists() else "ffprobe"


def _size(path, ffmpeg="ffmpeg"):
    out = subprocess.run(
        [_probe(ffmpeg), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:format=duration",
         "-of", "json", str(path)], capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)
    s = data["streams"][0]
    return s["width"], s["height"], float(data["format"].get("duration", 0))


def _frames(path, w, h, ffmpeg="ffmpeg"):
    """Кадр в секунду, серый и уменьшенный — потоком, без записи на диск.

    Декодирование программное: с аппаратным кадры приходится выгружать из
    видеопамяти, и на записи экрана это в тринадцать раз медленнее.
    """
    proc = subprocess.Popen(
        [ffmpeg, "-v", "error", "-threads", "0", "-i", str(path),
         "-vf", f"fps=1,scale={w}:{h}:flags=area,format=gray",
         "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    size = w * h
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, np.uint8).reshape(h, w)
    finally:
        proc.stdout.close()
        proc.wait()


def _cells(a):
    """Среднее по клеткам."""
    rows, cols = a.shape[0] // CELL, a.shape[1] // CELL
    return a[:rows * CELL, :cols * CELL].reshape(rows, CELL, cols, CELL).mean(axis=(1, 3))


def _spread(frame):
    """Разброс яркости по клеткам: пустой фон — ноль, текст и рисунки — выше."""
    f = frame.astype(np.float32)
    rows, cols = f.shape[0] // CELL, f.shape[1] // CELL
    return f[:rows * CELL, :cols * CELL].reshape(rows, CELL, cols, CELL).std(axis=(1, 3))


def _calm_runs(path, ffmpeg, should_stop, progress):
    """Спокойные отрезки записи: конец каждого — кандидат в слайды."""
    ow, oh, duration = _size(path, ffmpeg)
    h = int(round(W * oh / ow / 2) * 2)
    runs: list[Slide] = []
    prev = act = anchor = None
    calm_since = last_calm = None
    for i, frame in enumerate(_frames(path, W, h, ffmpeg)):
        if should_stop():
            raise InterruptedError
        if duration and i % 30 == 0:
            progress(min(1.0, i / duration))
        if prev is None:
            prev, calm_since, anchor = frame, 0.0, frame
            act = np.zeros(_cells(frame).shape, np.float32)
            continue
        d = _cells(np.abs(frame.astype(np.int16) - prev.astype(np.int16)))
        moved = d > STILL
        act = 0.97 * act + 0.03 * moved
        live = act > LIVE
        quiet = ~live
        calm = float((~moved[quiet]).mean()) >= CALM if quiet.any() else False
        if calm:
            if calm_since is None:
                calm_since, anchor = float(i - 1), prev
            # Перо пишет понемногу: каждый кадр меняет меньше порога, и отрезок
            # не рвался, пока лектор не отойдёт от слайда. Копим разницу с
            # началом отрезка: дописано заметно — это уже следующий этап.
            grown = _cells(np.abs(frame.astype(np.int16) - anchor.astype(np.int16)))
            if int(((grown > DIFF) & quiet).sum()) >= INK:
                if last_calm and last_calm[0] - calm_since >= MIN_CALM:
                    runs.append(Slide(calm_since, *last_calm))
                calm_since, anchor = float(i), frame
            last_calm = (float(i), frame, live.copy())
        else:
            if calm_since is not None and last_calm and last_calm[0] - calm_since >= MIN_CALM:
                runs.append(Slide(calm_since, *last_calm))
            calm_since = last_calm = None
        prev = frame
    if calm_since is not None and last_calm and last_calm[0] - calm_since >= MIN_CALM:
        runs.append(Slide(calm_since, *last_calm))
    progress(1.0)
    return runs, (ow, oh), h


def _dark(a, level=150):
    """Тёмное на светлом: текст, формулы, чернила. С запасом в точку —
    сжатие видео сдвигает края букв, и одно и то же пятно не должно
    считаться то исчезнувшим, то появившимся."""
    d = a < level
    grown = d.copy()
    grown[1:] |= d[:-1]; grown[:-1] |= d[1:]
    grown[:, 1:] |= d[:, :-1]; grown[:, :-1] |= d[:, 1:]
    return d, grown


def _match(a, b, limit):
    """Насколько b прокручен относительно a и какая доля строк совпала.

    Сдвиг s ≥ 0 значит: строки a начиная с s совпадают со строками b с нуля,
    то есть страницу пролистали вниз. Считаются только строки с текстом —
    пустые совпадают при любом сдвиге и ничего не доказывают.

    Прокрутка идёт на дробное число точек разбора, и строки букв при сдвиге
    на полточки расходятся на десятки уровней яркости. Поэтому кадры слегка
    размыты по вертикали, а совпадение строки считается относительно её же
    контраста.
    """
    def soft(x):
        x = x.astype(np.float32)
        y = x.copy()
        y[1:-1] = (x[:-2] + 2 * x[1:-1] + x[2:]) / 4
        return y

    a, b = soft(a), soft(b)
    n = a.shape[0]
    best = (0, 0.0)
    for sh in range(-limit, limit + 1):
        x, y = (a[sh:], b[:n - sh]) if sh >= 0 else (a[:n + sh], b[-sh:])
        if len(x) < n * 0.3:
            continue
        contrast = np.maximum(x.std(axis=1), y.std(axis=1))
        busy = contrast > 8
        if busy.sum() < 8:
            continue
        rows = np.abs(x - y).mean(axis=1)
        score = float(((rows < 0.3 * contrast) & busy).sum() / busy.sum())
        if score > best[1]:
            best = (sh, score)
    return best


def _stops(runs, box):
    """Спокойные отрезки без повторов: одинаковые склеены, дописанное пером
    заменяет прежний вид."""
    x0, y0, x1, y1 = box
    out: list[Slide] = []
    for cand in runs:
        area = cand.frame[y0:y1, x0:x1]
        if float(area.std()) < 5:
            continue                  # пустой экран: загрузка, чёрный кадр
        spread = _spread(area)
        if spread.size and float((spread < FLAT).mean()) < 0.3:
            continue                  # вебка во весь экран: ровного фона нет
        if not out:
            out.append(cand)
            continue
        last = out[-1]
        old = last.frame[y0:y1, x0:x1]
        d = _cells(np.abs(area.astype(np.int16) - old.astype(np.int16)))
        if float((d > DIFF).mean()) < SAME:
            last.end = cand.end
            continue
        # Дописано: всё, что было тёмным, осталось на месте, и прибавилось
        # новое. По клеткам, а не по точкам: курсор и подсветка кнопки
        # исчезают из одной-двух клеток. И только без сдвига — иначе
        # прокрученная страница текста тоже «сохраняет» свои тёмные клетки.
        old_dark, _ = _dark(old)
        new_dark, new_grown = _dark(area)
        had = _cells(old_dark.astype(np.float32))
        still = _cells((old_dark & new_grown).astype(np.float32))
        lost = (had > 0.02) & (still < had * 0.8)
        shift, _score = _match(old, area, 3)
        if shift == 0 and float(lost.mean()) <= 0.03 \
                and new_dark.sum() >= old_dark.sum():
            # Прежний вид — этап: лектор что-то сказал и дописал.
            cand.stages = last.stages + [(last.since, last.end, last.frame)]
            cand.start = last.start
            out[-1] = cand
            continue
        out.append(cand)
    for st in out:
        _prune(st, box)
    return out


def _added(a, b, box):
    """Сколько клеток области b дописано по сравнению с a.

    Считаем по тому, насколько клетка потемнела, а не по порогу «тёмное»:
    тонкий штрих пера в уменьшенном кадре становится светло-серым и порог
    не проходит, хотя дописано явно.
    """
    x0, y0, x1, y1 = box
    darker = _cells(a[y0:y1, x0:x1].astype(np.float32) - b[y0:y1, x0:x1].astype(np.float32))
    return int((darker > 6.0).sum())


def _prune(st, box):
    """Оставить этапы, между которыми дописано заметно, а не сдвинут курсор.

    Мелкие прибавки копятся: этап, после которого дописали чуть-чуть,
    сливается со следующим — остаётся момент, когда вид появился, и кадр,
    на котором дописано больше.
    """
    if not st.stages:
        return
    seq = st.stages + [(st.since, st.end, st.frame)]
    kept = [seq[0]]
    for since, end, frame in seq[1:]:
        if _added(kept[-1][2], frame, box) >= INK:
            kept.append((since, end, frame))
        else:
            kept[-1] = (kept[-1][0], end, frame)
    st.since = kept[-1][0]
    st.stages = kept[:-1]


@dataclass
class Sheet:
    """Одна картинка: слайд или страница, склеенная из прокрутки."""
    stops: list            # остановки по порядку
    offsets: list          # где каждая стоит на общем листе, в точках разбора

    @property
    def start(self):
        return min(s.start for s in self.stops)

    @property
    def end(self):
        return max(s.end for s in self.stops)


def _sheets(stops, box):
    """Остановки, связанные прокруткой, — один лист. Остальное — отдельные."""
    x0, y0, x1, y1 = box
    limit = int((y1 - y0) * 0.9)
    sheets: list[Sheet] = []
    for st in stops:
        area = st.frame[y0:y1, x0:x1]
        if sheets:
            cur = sheets[-1]
            prev = cur.stops[-1].frame[y0:y1, x0:x1]
            shift, score = _match(prev, area, limit)
            # Прокрутка — если совпало много строк и перекрытие не крохотное:
            # на узкой полоске перекрытия совпадения бывают случайными. Тот
            # же вид с правками — тоже этот лист, поздний вариант поверх.
            overlap = 1 - abs(shift) / (y1 - y0)
            if (shift != 0 and score >= 0.7 and overlap >= 0.35) or \
                    (shift == 0 and score >= 0.85):
                cur.stops.append(st)
                cur.offsets.append(cur.offsets[-1] + shift)
                continue
        sheets.append(Sheet([st], [0]))
    return sheets


def find(path, ffmpeg="ffmpeg", should_stop=lambda: False, progress=lambda f: None):
    """Слайды записи. Возвращает листы, размер кадра, высоту разбора и
    область содержимого в точках разбора."""
    runs, size, h = _calm_runs(path, ffmpeg, should_stop, progress)
    if not runs:
        return [], size, h, (0, 0, W, h)
    box = content_box(runs, h) or (0, 0, W, h)
    stops = _stops(runs, box)
    return _sheets(stops, box), size, h, box


def content_box(runs, small_h):
    """Где на экране содержимое: связная область, которая менялась.

    Клетка считается содержимым, если хоть раз менялась между спокойными
    отрезками и при этом не живая. Вебка живая и выпадает, логотип и рамки
    окон не меняются вовсе. Берётся самая большая связная группа таких
    клеток и те, что над или под ней: у обычного слайда заголовок отделён от
    текста неподвижной чертой и попадает в свою группу. Часы на панели задач
    и вебка тоже меняются, но стоят сбоку и в область не входят. Пометки на полях
    примыкают к странице и остаются внутри — обрезать по «часто менявшимся»
    клеткам было нельзя, поля меняются редко.
    """
    marks = []
    for a, b in zip(runs, runs[1:]):
        d = _cells(np.abs(a.frame.astype(np.int16) - b.frame.astype(np.int16)))
        marks.append((d > DIFF) & ~a.live & ~b.live)
    if len(marks) < 3:
        return None
    hot = np.sum(marks, axis=0) >= 1
    rows, cols = hot.shape
    seen = np.zeros_like(hot)
    groups = []
    for r in range(rows):
        for c in range(cols):
            if not hot[r, c] or seen[r, c]:
                continue
            group, stack = [], [(r, c)]
            seen[r, c] = True
            while stack:
                y, x = stack.pop()
                group.append((y, x))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < rows and 0 <= nx < cols and hot[ny, nx] \
                                and not seen[ny, nx]:
                            seen[ny, nx] = True
                            stack.append((ny, nx))
            groups.append(group)
    if not groups:
        return None
    main = max(groups, key=len)
    m0, m1 = min(x for _, x in main), max(x for _, x in main)

    def above_or_below(g):
        """Группа над или под главной: перекрывает её по ширине наполовину.
        Так к тексту слайда присоединяется заголовок, а вебка, часы и
        островки сбоку от страницы — нет."""
        g0, g1 = min(x for _, x in g), max(x for _, x in g)
        overlap = min(g1, m1) - max(g0, m0) + 1
        return overlap >= 0.5 * (g1 - g0 + 1)

    kept = [main] + [g for g in groups if g is not main
                     and len(g) >= max(4, 0.15 * len(main)) and above_or_below(g)]
    cells = [cell for g in kept for cell in g]
    if len(cells) < 0.1 * rows * cols:
        return None                   # содержимого почти нет — не режем
    ys = [y for y, _ in cells]
    xs = [x for _, x in cells]
    # Клетка запаса: буквы у края меняют клетку не целиком и туда не попадают.
    r0, r1 = max(0, min(ys) - 1), min(rows - 1, max(ys) + 1)
    c0, c1 = max(0, min(xs) - 1), min(cols - 1, max(xs) + 1)
    return (c0 * CELL, r0 * CELL, (c1 + 1) * CELL, (r1 + 1) * CELL)


def _grab(path, at, crop, w, h, ffmpeg):
    """Один кадр в полном разрешении, уже обрезанный, — массивом RGB."""
    out = subprocess.run(
        [ffmpeg, "-v", "error", "-ss", f"{at:.2f}", "-i", str(path),
         "-frames:v", "1", "-vf", crop, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True).stdout
    return np.frombuffer(out, np.uint8)[:w * h * 3].reshape(h, w, 3)


def _write(img, file, ffmpeg):
    h, w = img.shape[:2]
    subprocess.run(
        [ffmpeg, "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{w}x{h}", "-i", "-", "-y", str(file)],
        input=np.ascontiguousarray(img).tobytes(), check=True)


def _cut(canvas, view):
    """Длинный лист режется на куски в высоту экрана — по пустому промежутку
    между строками, а не поперёк букв."""
    h = canvas.shape[0]
    if h <= view * 1.6:
        return [canvas]
    gray = canvas.mean(axis=2)
    busy = gray.std(axis=1)
    pieces, top = [], 0
    while h - top > view * 1.6:
        aim = top + view
        lo, hi = aim - int(view * 0.15), aim + int(view * 0.15)
        row = lo + int(np.argmin(busy[lo:hi]))
        pieces.append(canvas[top:row])
        top = row
    pieces.append(canvas[top:])
    return pieces


def _refine(frames, rough_offsets, ky, h):
    """Сдвиги остановок листа в полном разрешении."""
    offsets = [0]
    for k in range(1, len(frames)):
        rough = int(round((rough_offsets[k] - rough_offsets[k - 1]) * ky))
        if rough == 0:
            offsets.append(offsets[-1])
            continue
        pad = int(ky * 2) + 2
        a = frames[k - 1].mean(axis=2)
        b = frames[k].mean(axis=2)
        # Ищем точный сдвиг рядом с грубым: сдвигаем b и считаем совпадение.
        best, score = rough, -1.0
        for sh in range(rough - pad, rough + pad + 1):
            if abs(sh) >= h * 0.95:
                continue
            x, y = (a[sh:], b[:h - sh]) if sh >= 0 else (a[:h + sh], b[-sh:])
            contrast = np.maximum(x.std(axis=1), y.std(axis=1))
            busy = contrast > 8
            if busy.sum() < 8:
                continue
            rows = np.abs(x - y).mean(axis=1)
            sc = float(((rows < 0.3 * contrast) & busy).sum() / busy.sum())
            if sc > score:
                best, score = sh, sc
        offsets.append(offsets[-1] + best)
    return offsets


def _fixed_edges(sheets, grabbed, w, h, ky):
    """Панели по краям, которые при прокрутке стоят на месте: инструменты
    просмотрщика сбоку, плашка «идёт показ экрана» снизу.

    Страницу листают, и всё на ней сдвигается; панели остаются. Для каждого
    столбца и строки считаем долю непустых точек, не изменившихся ни на одной
    остановке прокрученного листа. У текста страницы она около нуля, у панели
    больше половины. Ищем такие полосы только у краёв и срезаем кадр до них —
    вместе с тем, что между полосой и краем.

    Смотрим только на прокрученные листы: у презентации рамка и логотип
    шаблона тоже неподвижны, но это часть слайда.
    """
    fixed = np.zeros((h, w))
    filled = np.zeros((h, w))
    for sheet, frames in zip(sheets, grabbed):
        if (max(sheet.offsets) - min(sheet.offsets)) * ky < 120:
            continue
        stack = np.stack(frames).mean(axis=3)
        some = (stack < 235).any(axis=0)
        fixed += (stack.max(axis=0) - stack.min(axis=0) < 16) & some
        filled += some
    if not filled.any():
        return 0, 0, w, h

    def share(fx, fl):
        """Доля неподвижного; почти пустые столбцы — ни то ни сё (None):
        по паре точек доля случайна."""
        frac = np.convolve(fx, np.ones(5), mode="same") / \
            np.maximum(np.convolve(fl, np.ones(5), mode="same"), 1)
        enough = np.convolve(fl, np.ones(5), mode="same") >= 100
        return [f if ok else None for f, ok in zip(frac, enough)]

    def band(frac, order):
        """Идём от края внутрь. Неподвижное — панель, пустое пропускаем;
        как только пошло содержимое страницы, панель кончилась."""
        edge, content = None, 0
        for i in order:
            f = frac[i]
            if f is None:
                continue
            if f > 0.4:
                edge, content = i, 0
            else:
                content += 1
                if content > 8:
                    break
        return edge

    def inner(frac, n):
        reach = int(n * 0.12)
        lo = band(frac, range(reach))
        hi = band(frac, range(n - 1, n - 1 - reach, -1))
        return (lo + 5 if lo is not None else 0), (hi - 4 if hi is not None else n)

    left, right = inner(share(fixed.sum(0), filled.sum(0)), w)
    rows = share(fixed[:, left:right].sum(1), filled[:, left:right].sum(1))
    top, bottom = inner(rows, h)
    return left, top, right, bottom


def save(path, sheets, size, small_h, box, out_dir, base, ffmpeg="ffmpeg",
         should_stop=lambda: False, progress=lambda f: None, label="Слайд",
         tail=""):
    """Сохранить листы в полном разрешении.

    Лист из одной остановки — это кадр, обрезанный по содержимому. Лист из
    прокрутки склеивается: каждая остановка ложится на своё место, поздняя
    поверх ранней — на ней больше пометок. Сдвиги уточняются в полном
    разрешении: в разборе они известны с точностью до четырёх-пяти точек.
    """
    ow, oh = size
    kx, ky = ow / W, oh / small_h
    x0, y0 = int(box[0] * kx), int(box[1] * ky)
    x1, y1 = min(ow, int(box[2] * kx)), min(oh, int(box[3] * ky))
    w, h = (x1 - x0) // 2 * 2, (y1 - y0) // 2 * 2
    crop = f"crop={w}:{h}:{x0}:{y0}"
    out_dir.mkdir(parents=True, exist_ok=True)

    grabbed = []
    for i, sheet in enumerate(sheets):
        if should_stop():
            raise InterruptedError
        progress(0.7 * i / max(1, len(sheets)))
        grabbed.append([_grab(path, max(0.0, st.end - 0.5), crop, w, h, ffmpeg)
                        for st in sheet.stops])
    ex0, ey0, ex1, ey1 = _fixed_edges(sheets, grabbed, w, h, ky)
    grabbed = [[f[ey0:ey1, ex0:ex1] for f in frames] for frames in grabbed]
    ow_crop, oh_crop = w, h
    w, h = ex1 - ex0, ey1 - ey0

    images = []            # (картинка, когда появилась, когда ушла, этапы)
    for i, (sheet, frames) in enumerate(zip(sheets, grabbed)):
        if should_stop():
            raise InterruptedError
        progress(0.7 + 0.3 * i / max(1, len(sheets)))
        offsets = _refine(frames, sheet.offsets, ky, h)
        top = min(offsets)
        height = max(offsets) - top + h
        canvas = np.full((height, w, 3), 255, np.uint8)
        # Поздняя остановка поверх ранней: на ней больше пометок.
        for f, off in zip(frames, offsets):
            canvas[off - top:off - top + h] = f
        # Этапы дописывания — отдельными кадрами, без склейки: каждый
        # показывает, что было на экране, пока об этом говорили.
        stages = [(since, end) for st in sheet.stops for since, end, _ in st.stages]
        # Готовый вид — с того момента, как дописан, если было что дописывать.
        shown = max((st.since for st in sheet.stops if st.stages),
                    default=sheet.start)
        for k, piece in enumerate(_cut(canvas, h)):
            images.append((piece, shown, sheet.end, stages if k == 0 else []))

    width = 3 if len(images) >= 100 else 2
    saved = []
    for n, (img, start, end, stages) in enumerate(images, 1):
        name = f"{label} {n:0{width}d}{tail} — {base}.png"
        _write(img, out_dir / name, ffmpeg)
        saved.append({"n": n, "stage": 0, "file": name, "start": start, "end": end})
        for k, (since, until) in enumerate(stages, 1):
            if should_stop():
                raise InterruptedError
            frame = _grab(path, max(0.0, until - 0.5), crop, ow_crop, oh_crop, ffmpeg)
            frame = frame[ey0:ey1, ex0:ex1]
            name = f"{label} {n:0{width}d}.{k}{tail} — {base}.png"
            _write(frame, out_dir / name, ffmpeg)
            saved.append({"n": n, "stage": k, "file": name,
                          "start": since, "end": until})
    progress(1.0)
    return saved


if __name__ == "__main__":
    import sys, time
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    t = time.time()
    found, size, sh, box = find(src)
    print(f"листов: {len(found)} за {time.time() - t:.1f} с")
    t = time.time()
    saved = save(src, found, size, sh, box, out, src.stem)
    print(f"сохранено {len(saved)} картинок за {time.time() - t:.1f} с, область {box}")
    for s in saved:
        print(f"  {s['n']:3}  {int(s['start'] // 60):02d}:{int(s['start'] % 60):02d}"
              f"–{int(s['end'] // 60):02d}:{int(s['end'] % 60):02d}  {s['file']}")
