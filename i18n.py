"""Язык интерфейса. Ключ перевода — сама русская строка."""
from PySide6.QtCore import QLocale, QSettings

LANGS = ("ru", "en")

EN = {
    "Куда ставятся новые модели": "Where new models go",
    "Лекции": "Lectures",
    "Модели": "Models",
    "Приложение": "App",
    "Папка для лекций": "Lectures folder",
    "Если не выбрана предустановка": "When no preset is chosen",
    "Настройки…": "Settings…",
    "Сначала скачайте {name} в настройках.": "Download {name} in Settings first.",
    "Поддержать": "Support",
    "Сбросить": "Reset",
    " — недоступна": " — unavailable",
    "Папка недоступна: {where}": "Folder unavailable: {where}",
    "{gb} ГБ, установится в {where}": "{gb} GB, will be installed to {where}",
    "В {where}": "To {where}",
    "В другую папку…": "To another folder…",
    "Папка для модели": "Folder for this model",
    "Оформление": "Appearance",
    "Цвета окна": "Window colours",
    "Как в системе": "System",
    "Светлое": "Light",
    "Тёмное": "Dark",
    "{mb} МБ/с": "{mb} MB/s",
    "МБ/с": "MB/s",
    "ещё {h} ч {m} мин": "{h} h {m} min left",
    "ещё {m} мин": "{m} min left",
    "в очереди": "queued",
    ", перед ней {n}": ", {n} ahead",
    ", следующая": ", next",
    "не вышло: {e}": "failed: {e}",
    "Выбрать папку…": "Choose folder…", "Папка для моделей": "Models folder",
    "Б": "B", "КБ": "KB", "МБ": "MB", "ГБ": "GB",
    "{a} из {gb} ГБ": "{a} of {gb} GB",
    "Всего ": "Total ",
    "  ↳ «{name}» заняло {span}": "  ↳ «{name}» took {span}",
    "Запись": "Recording",
    "Перетащите запись лекции": "Drop a lecture recording",
    "видео или аудио": "video or audio",
    "Выбрать файл…": "Choose file…",
    "Запись лекции": "Lecture recording",
    "Видео и аудио": "Video and audio",
    "Что нужно": "What you need",
    "Слайды": "Slides",
    "Название": "Title",
    "Предустановка": "Preset",
    "Предустановки": "Presets",
    "Нет": "None",
    "Добавить…": "Add…",
    "Новая…": "New…",
    "Новая предустановка": "New preset",
    "Создать": "Create",
    "Разобрать": "Process",
    "Отмена": "Cancel",
    "Остановка…": "Stopping…",
    "Отменено.": "Cancelled.",
    "Не получилось": "Something went wrong",
    "Ход работы": "Progress",
    "Настройки": "Settings",
    "История": "History",
    "Разобранных лекций пока нет": "No processed lectures yet",
    "Свернуть или показать левую панель": "Hide or show the left panel",
    "Расшифровка": "Transcript",
    "Слайд": "Slide",
    "этап": "stage",
    "Показать в Finder": "Show in Finder",
    "Скопировать": "Copy",
    "Скопировано": "Copied",
    "Распознавание речи": "Speech recognition",
    "Конспект": "Notes",
    "Использовать": "Use",
    "Используется": "In use",
    "Скачать": "Download",
    "Удалить": "Delete",
    "Удаление модели": "Delete model",
    "Удалить {name} с диска?": "Delete {name} from disk?",
    "Не скачалось": "Download failed",
    "Нужна модель": "Model needed",
    "Сначала скачайте {name} во вкладке «Настройки».":
        "Download {name} in the Settings tab first.",
    "Папка": "Folder",
    "Папка для расшифровок и слайдов": "Folder for transcripts and slides",
    "Выбрать…": "Choose…",
    "Открыть": "Open",
    "Язык": "Language",
    "Язык интерфейса и конспекта": "Interface and notes language",
    "О программе {name}": "About {name}",
    "Закрыть": "Close",
    "Поиск слайдов…": "Looking for slides…",
    "Поиск слайдов": "Looking for slides",
    "Извлечение звука": "Extracting audio",
    "Распознавание речи…": "Speech recognition…",
    "  кусок сорвался в повтор, распознаётся заново":
        "  a piece got stuck in a loop, recognising again",
    "  повтор остался, из куска берётся по реплике":
        "  the loop remained, keeping one line of each",
    "  реплик: {n}": "  lines: {n}",
    "  звуковой дорожки нет": "  no audio track",
    "  слайды не получились: {e}": "  slides failed: {e}",
    "  слайдов: {n}": "  slides: {n}",
    "Конспект…": "Notes…",
    "  конспект не получился: {e}": "  notes failed: {e}",
    "Сохранено: ": "Saved: ",
    "Сборка PDF": "Building PDF",
    "  PDF не получился: {e}": "  PDF failed: {e}",
    "Речи в записи нет.": "There is no speech in the recording.",
}

_lang = None


def current():
    """Настройка важнее системного языка."""
    global _lang
    if _lang is None:
        saved = QSettings("local", "Lectures").value("lang", "")
        if saved in LANGS:
            _lang = saved
        else:
            _lang = "ru" if QLocale.system().language() == QLocale.Russian else "en"
    return _lang


def set_current(lang):
    global _lang
    if lang in LANGS:
        _lang = lang
        QSettings("local", "Lectures").setValue("lang", lang)


_BACK = {v: k for k, v in EN.items() if v != k}


def key_of(text):
    """Русский ключ по видимой надписи — для перевода собранного окна."""
    if text in EN:
        return text
    return _BACK.get(text)


def t(s):
    """Нет в словаре — возвращаем как есть."""
    return EN.get(s, s) if current() == "en" else s


def tf(fmt, **kw):
    """Перевод заготовки со скобками и подстановка значений."""
    return t(fmt).format(**kw)


# Подписи хода загрузки моделей — тоже на языке приложения.
import models_home  # noqa: E402

models_home.set_translator(t)
