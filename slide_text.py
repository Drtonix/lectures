"""Текст со слайдов: встроенное в macOS распознавание (Vision), без сети.

Кадр записи сжат, и буквы на нём мелкие: «б» расплывается в «о», «и» в «н».
Слово, которого нет в словаре macOS, пробуем починить заменой одной такой
буквы на её пару. Подсказки самого словаря не берём: из «столоцу» он делает
«столицу» — настоящее слово, но чужое, и это хуже опечатки.
Обрывки формул выбрасываются: прочитать их всё равно не выходит, а сами
формулы видны на картинке.
"""
import re

# Пары букв, которые распознавание путает на мелком шрифте.
LOOKALIKE = [("о", "б"), ("н", "и"), ("п", "л"), ("ш", "щ"), ("ь", "ы"),
             ("ь", "ъ"), ("з", "в"), ("е", "с")]
SWAP = {}
for x, y in LOOKALIKE:
    SWAP.setdefault(x, []).append(y)
    SWAP.setdefault(y, []).append(x)
WORD = re.compile(r"[А-Яа-яЁё]{4,}")


def _image(path):
    import Quartz
    from Foundation import NSURL
    src = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(str(path)), None)
    return Quartz.CGImageSourceCreateImageAtIndex(src, 0, None) if src else None


def _speller():
    try:
        from AppKit import NSSpellChecker
        sc = NSSpellChecker.sharedSpellChecker()
        return sc if "ru" in sc.availableLanguages() else None
    except Exception:
        return None


def _known(sc, word):
    miss = sc.checkSpellingOfString_startingAt_language_wrap_inSpellDocumentWithTag_wordCount_(
        word, 0, "ru", False, 0, None)[0]
    return miss.length == 0


def _fix_word(sc, word):
    if _known(sc, word):
        return word
    for i, ch in enumerate(word.lower()):
        for other in SWAP.get(ch, ()):
            if word[i].isupper():
                other = other.upper()
            cand = word[:i] + other + word[i + 1:]
            if _known(sc, cand):
                return cand
    return word


def _texty(line):
    """Строка — текст, а не обрывок формулы: больше половины — буквы
    и есть хоть одно слово."""
    chars = [c for c in line if not c.isspace()]
    letters = sum(c.isalpha() for c in chars)
    return bool(chars) and letters >= len(chars) * 0.5 and re.search(r"[^\W\d_]{3,}", line)


def read(path, min_confidence=0.4):
    """Строки слайда сверху вниз."""
    import Vision
    img = _image(path)
    if img is None:
        return []
    req = Vision.VNRecognizeTextRequest.alloc().init()
    # Fast калечит кириллицу: «KaK A noxyAen» вместо «Как я похудел».
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setRecognitionLanguages_(["ru-RU", "en-US"])
    req.setUsesLanguageCorrection_(True)
    Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
        img, None).performRequests_error_([req], None)
    lines = []
    for obs in (req.results() or []):
        cand = obs.topCandidates_(1)
        if cand and cand[0].confidence() >= min_confidence:
            lines.append(" ".join(cand[0].string().split()))
    # Слово, разорванное переносом, склеиваем до проверки словарём:
    # «ооль-» и «ше» по отдельности ему не узнать.
    out = []
    for line in lines:
        if out and re.search(r"[А-Яа-яЁёA-Za-z]-$", out[-1]):
            out[-1] = out[-1][:-1] + line
        else:
            out.append(line)
    sc = _speller()
    if sc is not None:
        out = [WORD.sub(lambda m: _fix_word(sc, m.group(0)), x) for x in out]
    return [x for x in out if _texty(x)]
