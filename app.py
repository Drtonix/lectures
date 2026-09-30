"""Окно Lectures: запись слева, расшифровка и слайды справа."""
import json, os, re, subprocess, sys, time, traceback
from pathlib import Path
from PySide6.QtCore import QEvent, QObject, Qt, QPointF, QRectF, QSettings, QSize, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (QAction, QColor, QDesktopServices, QIcon, QPainter,
                           QKeySequence, QPainterPath, QPen, QPixmap, QTransform)
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog,
                               QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMenu, QListView, QListWidget,
                               QListWidgetItem, QMenuBar, QMessageBox,
                               QPlainTextEdit, QPushButton, QScrollArea,
                               QSizePolicy, QSplitter, QStackedWidget, QTextBrowser,
                               QVBoxLayout, QWidget)
import _style
from _style import STYLE
from i18n import t, tf
import i18n
import models_store

APP = "Lectures"
AUTHOR = "DrTonix"
SITE = "bdub.space"
URL = "https://bdub.space"

OUT_DIR = Path.home() / "Documents" / "Lectures"
MEDIA_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".flv", ".ts",
             ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
ACCENT = "#f5cf6b"

THEMES = ("system", "light", "dark")


def theme():
    name = QSettings("local", "Lectures").value("theme", "system")
    return name if name in THEMES else "system"


def skin():
    name = theme()
    if name != "system":
        return name
    from PySide6.QtGui import QGuiApplication
    return "dark" if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"


def themed(css):
    return _style.light(css) if skin() == "light" else css


def tone(hex_):
    return QColor(_style.light_hex(hex_) if skin() == "light" else hex_)


def ink(alpha):
    """Полупрозрачная заливка: белая на тёмном, чёрная на светлом."""
    return QColor(0, 0, 0, int(alpha * 0.8)) if skin() == "light" else QColor(255, 255, 255, alpha)


EXTRA = """
QLineEdit {
    background: rgba(255,255,255,0.07);
    border: none; border-radius: 10px;
    padding: 11px 13px; color: #e9ebef; font-size: 13px;
}
QLineEdit:focus { background: rgba(255,255,255,0.10); }
QPushButton#danger {
    background: rgba(255,255,255,0.10);
    color: #e9ebef;
    font-weight: 500;
}
QPushButton#danger:hover { background: rgba(255,255,255,0.15); }
QFrame#panel {
    background: #232327;
    border: none;
    border-radius: 14px;
}
QScrollArea#feed, QWidget#feedInner { background: transparent; border: none; }
QLabel#dim { color: #9aa0a8; font-size: 12px; }
QTextBrowser {
    background: transparent;
    border: none;
    color: #dfe3ea;
    font-size: 13px;
    selection-background-color: rgba(245,207,107,0.45);
}
/* Лента слайдов: без рамок, выбранный — подложкой акцента. */
QListWidget#history {
    background: #1a1a1d;
    border: none;
    border-radius: 12px;
    padding: 6px;
    color: #c3c8d0;
    font-size: 12px;
}
QListWidget#history::item { padding: 8px 10px; border-radius: 8px; }
QListWidget#history::item:hover    { background: rgba(255,255,255,0.06); }
QListWidget#history::item:selected { background: rgba(245,207,107,0.30); color: #ffffff; }
QListWidget#slides {
    background: transparent;
    border: none;
    color: #a9adb5;
    font-size: 12px;
}
QListWidget#slides::item { border-radius: 10px; padding: 6px; }
QListWidget#slides::item:hover    { background: rgba(255,255,255,0.05); }
QListWidget#slides::item:selected { background: rgba(245,207,107,0.30); color: #ffffff; }
QSplitter::handle { background: transparent; width: 14px; }
/* Кнопка-поле: как QLineEdit#small рядом, только нажимается. */
QPushButton#field {
    background: rgba(255,255,255,0.07);
    border: none; border-radius: 10px;
    padding: 0 11px;
    color: #e9ebef; font-size: 13px;
}
QPushButton#field:hover    { background: rgba(255,255,255,0.10); }
QPushButton#field:disabled { color: rgba(233,235,239,0.35); }
/* Меню — как в Konspekt: скруглённая подложка, пункт подсвечен акцентом. */
QMenu {
    background: #2c2c31;
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 9px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 22px 6px 11px;
    border-radius: 6px;
    color: #e9ebef;
    font-size: 13px;
}
QMenu::item:selected { background: #f5cf6b; color: #1e1e20; }
QPushButton#iconbtn {
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 0;
}
QPushButton#iconbtn:hover { background: rgba(255,255,255,0.08); }
QPushButton#settings {
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 6px 10px 6px 6px;
    color: #9aa0a8;
    font-size: 13px;
    text-align: left;
}
QPushButton#settings:hover { background: rgba(255,255,255,0.08); color: #e9ebef; }
"""

# MLX обходит граф вычислений рекурсией, и на длинной записи ему не хватает
# стека рабочего потока: у созданного потока на macOS полмегабайта, и
# приложение падает с «Bus error». Просим с запасом.
STACK = 64 * 1024 * 1024

# Ширина полей «Предустановка» и «Название»: одинаковая, и в неё помещается
# обычное название предмета вроде «Основы менеджмента».
FIELD = 200


def app_icon():
    """Значок из бандла, при запуске из исходников — из проекта."""
    here = Path(__file__).resolve().parent
    for p in (here.parent / "AppIcon.icns", here / "icon" / "AppIcon.icns"):
        if p.exists():
            return QIcon(str(p))
    return QIcon()


def _pixmap(px):
    """Холст в плотности экрана: иначе значок мылит на двукратном дисплее."""
    app = QApplication.instance()
    dpr = float(app.devicePixelRatio()) if app else 2.0
    pm = QPixmap(int(px * dpr), int(px * dpr))
    pm.fill(Qt.GlobalColor.transparent)
    pm.setDevicePixelRatio(dpr)
    return pm


def _icon_sidebar(px=18, color="#9aa0a8"):
    """Прямоугольник с левой колонкой; рамка внутрь на полтолщины, иначе срез."""
    pm = _pixmap(px)
    pt = QPainter(pm)
    pt.setRenderHint(QPainter.RenderHint.Antialiasing)
    w = px * 0.09
    pen = QPen(QColor(color)); pen.setWidthF(w)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pt.setPen(pen)
    m = px * 0.13 + w / 2
    rect = QRectF(m, m, px - 2 * m, px - 2 * m)
    r = px * 0.14
    pt.drawRoundedRect(rect, r, r)
    x = rect.left() + rect.width() * 0.38
    # линию не ведём до самой рамки, иначе она наезжает на скругления
    pt.drawLine(QPointF(x, rect.top() + r * 0.5), QPointF(x, rect.bottom() - r * 0.5))
    pt.end()
    return QIcon(pm)


def _icon_gear(px=18, color="#9aa0a8"):
    """Шестерёнка тем же контуром, что и значок боковой панели."""
    pm = _pixmap(px)
    pt = QPainter(pm)
    pt.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color)); pen.setWidthF(px * 0.09)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pt.setPen(pen)
    c = QPointF(px / 2, px / 2)
    body = QPainterPath(); body.addEllipse(c, px * 0.27, px * 0.27)
    for k in range(8):
        tooth = QPainterPath()
        tooth.addRoundedRect(QRectF(-px * 0.075, -px * 0.40, px * 0.15, px * 0.16), px * 0.03, px * 0.03)
        body = body.united(QTransform().translate(c.x(), c.y()).rotate(k * 45).map(tooth))
    hole = QPainterPath(); hole.addEllipse(c, px * 0.10, px * 0.10)
    pt.drawPath(body.subtracted(hole))
    pt.end()
    return QIcon(pm)


class SettingsWindow(QDialog):
    """Настройки — своим окном, как принято на Mac. Вкладкой в левой колонке
    карточкам было тесно, а сама колонка расширялась под них при переходе."""

    def __init__(self, parent, page):
        super().__init__(parent)
        self.setObjectName("root")
        self.setWindowTitle(t("Настройки"))
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 16, 16, 16)
        box.addWidget(page)
        self.resize(500, 680)


class Bar(QWidget):
    """Полоса хода работы. Своя: штатная обрезает бегущий отрезок по прямой."""

    H = 6

    def __init__(self):
        super().__init__()
        self.setFixedHeight(self.H)
        self._busy = False
        self._pos = 0.0
        self._value = 0.0
        self._shown = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_busy(self, on):
        self._busy = on
        self._timer.start(16) if on else self._timer.stop()
        self.update()

    def set_progress(self, cur, total):
        # Значение приходит рывками, полоса идёт к нему плавно.
        self._busy = False
        self._value = (cur / total) if total else 0.0
        if self._value <= self._shown:
            self._shown = self._value
        if not self._timer.isActive():
            self._timer.start(16)
        self.update()

    def _tick(self):
        if self._busy:
            self._pos = (self._pos + 0.011) % 1.0
        else:
            if abs(self._value - self._shown) < 0.0002:
                self._shown = self._value
                self._timer.stop()
            else:
                self._shown += (self._value - self._shown) * 0.08
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = h / 2
        track = QPainterPath()
        track.addRoundedRect(QRectF(0, 0, w, h), r, r)
        p.setClipPath(track)
        p.fillPath(track, ink(16))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ACCENT))
        if self._busy:
            seg = w * 0.32
            x = self._pos * (w + seg) - seg
            p.drawRoundedRect(QRectF(x, 0, seg, h), r, r)
        elif self._shown > 0:
            p.drawRoundedRect(QRectF(0, 0, max(h, w * self._shown), h), r, r)
        p.end()


def for_reading(md):
    """Расшифровка для буфера обмена — без строк с картинками: вставленные
    в чат, они остались бы битыми ссылками."""
    return re.sub(r"(?m)^!\[[^\]]*\]\(.*\)\n\n?", "", md)


def for_view(md):
    """Для окна — ещё и без текста слайдов: сами слайды во вкладке рядом."""
    return re.sub(r"(?m)^> .*\n(\n)?", "", for_reading(md))


def open_link(url):
    """Ссылки из ответа модели и чужих страниц открываются, только если это
    веб-адрес: file:///…/что-то.app по щелчку запустил бы программу."""
    url = QUrl(url) if isinstance(url, str) else url
    if url.scheme().lower() in ("http", "https", "mailto"):
        QDesktopServices.openUrl(url)


# Дата в конце имени; прежние разборы — с датой в начале, их тоже читаем.
_STAMP = r"(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})"
_WORD = r"(?:Расшифровка|Transcript)"
SAVED = re.compile(rf"^{_WORD}( .+)? — {_STAMP}\.md$")
SAVED_OLD = re.compile(rf"^{_STAMP} — {_WORD}( .+)?\.md$")


def saved_name(filename):
    """(дата, название) из имени расшифровки или None."""
    m = SAVED.match(filename)
    if m:
        return m.group(2), (m.group(1) or "").strip()
    m = SAVED_OLD.match(filename)
    if m:
        return m.group(1), (m.group(2) or "").strip()
    return None


SLIDE_NO = re.compile(r"(?:^| — )\S+ (\d+)(?:\.(\d+))?(?= |$)")


def _folder_title(folder, base):
    """Название из имени папки записи: «Название — дата» или «дата — Название»."""
    if folder.endswith(" — " + base):
        return folder[:-len(" — " + base)]
    if folder.startswith(base + " — "):
        return folder[len(base + " — "):]
    return ""


def slide_order(path):
    """Слайды по ходу лекции: этапы дописывания раньше готового вида."""
    m = SLIDE_NO.search(Path(path).stem)
    if not m:
        return (10 ** 6, 0, 0)
    return (int(m.group(1)), 0 if m.group(2) else 1, int(m.group(2) or 0))


def slide_label(path):
    n, final, k = slide_order(path)
    return f"{t('Слайд')} {n}" + ("" if final else f" · {t('этап')} {k}")


class PresetDialog(QDialog):
    """Новая предустановка: название и папка в одном окне."""

    def __init__(self, parent, start_dir):
        super().__init__(parent)
        self.setWindowTitle(t("Новая предустановка"))
        self.setObjectName("root")
        self.setStyleSheet(parent.styleSheet())
        self.folder = ""
        self._start = str(start_dir)
        box = QVBoxLayout(self)
        box.setContentsMargins(20, 18, 20, 18); box.setSpacing(10)
        cap = QLabel(t("Название")); cap.setObjectName("section")
        box.addWidget(cap)
        self.name = QLineEdit()
        self.name.textChanged.connect(self._sync)
        box.addWidget(self.name)
        cap = QLabel(t("Папка")); cap.setObjectName("section")
        box.addSpacing(4); box.addWidget(cap)
        self.pick = QPushButton(t("Выбрать…")); self.pick.setObjectName("field")
        self.pick.setFixedHeight(38); self.pick.setCursor(Qt.PointingHandCursor)
        self.pick.clicked.connect(self._choose)
        box.addWidget(self.pick)
        row = QHBoxLayout(); row.addStretch(); row.setSpacing(8)
        cancel = QPushButton(t("Отмена")); cancel.setObjectName("cardbtn")
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton(t("Создать")); self.ok.setObjectName("cardbtnAccent")
        self.ok.setDefault(True); self.ok.clicked.connect(self.accept)
        row.addWidget(cancel); row.addWidget(self.ok)
        box.addSpacing(8); box.addLayout(row)
        self.setFixedWidth(420)
        self._sync()

    def _choose(self):
        d = QFileDialog.getExistingDirectory(self, t("Папка"), self.folder or self._start)
        if d:
            self.folder = d
            # Длинный путь — с многоточием в середине, чтобы видно было и начало, и папку.
            shown = d.replace(str(Path.home()), "~")
            self.pick.setText(self.pick.fontMetrics().elidedText(
                shown, Qt.ElideMiddle, self.pick.width() - 24))
        self._sync()

    def _sync(self):
        self.ok.setEnabled(bool(self.name.text().strip()) and bool(self.folder))

    def ask(self):
        import pipeline
        if self.exec() != QDialog.Accepted:
            return None
        name = pipeline.clean_title(self.name.text())
        return (name, self.folder) if name and self.folder else None


class Worker(QThread):
    line = Signal(str)
    step = Signal(str, int, int)
    done = Signal(dict)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, source, out_dir, title, own_folder, with_slides, with_summary,
                 model_id):
        super().__init__()
        self.title, self.own_folder = title, own_folder
        self.setStackSize(STACK)
        self.source, self.out_dir = source, out_dir
        self.with_slides, self.with_summary = with_slides, with_summary
        self.model_id = model_id
        self._stop = False
        self._t0 = 0.0
        self._stage_name, self._stage_t0 = "", 0.0

    def stop(self):
        self._stop = True

    @staticmethod
    def _span(sec):
        h, m, s = int(sec // 3600), int(sec // 60) % 60, int(sec) % 60
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    def _log(self, msg):
        self.line.emit(f"[{self._span(time.monotonic() - self._t0)}] {msg}")

    def _stage(self, name, cur, total):
        now = time.monotonic()
        if name != self._stage_name:
            self._close_stage(now)
            self._stage_name, self._stage_t0 = name, now
        self.step.emit(name, cur, total)

    def _close_stage(self, now):
        if self._stage_name:
            self._log(tf("  ↳ «{name}» заняло {span}", name=self._stage_name,
                         span=self._span(now - self._stage_t0)))

    def run(self):
        self._t0 = self._stage_t0 = time.monotonic()
        import pipeline
        try:
            r = pipeline.process(self.source, self.out_dir, title=self.title,
                                 own_folder=self.own_folder,
                                 with_slides=self.with_slides,
                                 with_summary=self.with_summary,
                                 model_id=self.model_id,
                                 log=self._log, stage=self._stage,
                                 should_stop=lambda: self._stop)
            self._close_stage(time.monotonic())
            self._log(t("Всего ") + self._span(time.monotonic() - self._t0))
            self.done.emit(r)
        except pipeline.Cancelled:
            self.cancelled.emit()
        except Exception as e:
            self.failed.emit(f"{e}\n\n{traceback.format_exc()}")


class FitWidth(QObject):
    """Прокручиваемая панель не уже своего содержимого.

    Разделитель позволял сузить панель меньше, чем нужно карточкам: правый
    край обрезался, а скрытая горизонтальная прокрутка сдвигала всё меню вбок
    при каждом щелчке, когда Qt показывал элемент в фокусе.
    """

    def __init__(self, scroll):
        super().__init__(scroll)
        self.scroll = scroll
        scroll.widget().installEventFilter(self)
        self.fit()

    def eventFilter(self, obj, e):
        if e.type() == QEvent.LayoutRequest:
            QTimer.singleShot(0, self.fit)
        return False

    def fit(self):
        bar = self.scroll.verticalScrollBar().sizeHint().width()
        need = self.scroll.widget().minimumSizeHint().width() + bar + 2 * self.scroll.frameWidth()
        if self.scroll.minimumWidth() != need:
            self.scroll.setMinimumWidth(need)
        self.scroll.horizontalScrollBar().setValue(0)


class DownloadWorker(QThread):
    # qint64: у Qt int тридцатидвухбитный, и 16 ГБ в него не влезают.
    progress = Signal("qint64", "qint64")
    done = Signal(bool, str)

    def __init__(self, repo, where=None):
        super().__init__()
        self.repo, self.where = repo, where
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            ok = models_store.download(
                self.repo, on_progress=lambda a, b: self.progress.emit(int(a), int(b)),
                should_stop=lambda: self._stop, where=self.where)
            self.done.emit(bool(ok), "")
        except Exception as e:
            self.done.emit(False, f"{type(e).__name__}: {e}")


class Drop(QFrame):
    """Место для записи: сюда её бросают, здесь видно, что выбрано."""
    picked = Signal(Path)

    def __init__(self):
        super().__init__()
        self.setObjectName("drop")
        self.setAcceptDrops(True)
        self.setMinimumHeight(120)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 18); v.setSpacing(6)
        v.addStretch()
        self.title = QLabel(t("Перетащите запись лекции"))
        self.title.setObjectName("dropTitle")
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setWordWrap(True)
        self.hint = QLabel(t("видео или аудио"))
        self.hint.setObjectName("dropHint")
        self.hint.setAlignment(Qt.AlignCenter)
        v.addWidget(self.title); v.addWidget(self.hint)
        v.addSpacing(6)
        row = QHBoxLayout(); row.addStretch()
        self.pick = QPushButton(t("Выбрать файл…"))
        self.pick.setCursor(Qt.PointingHandCursor)
        row.addWidget(self.pick); row.addStretch()
        v.addLayout(row)
        v.addStretch()

    def _lit(self, on):
        self.setObjectName("dropOn" if on else "drop")
        self.setStyle(self.style())            # перечитать оформление под новое имя

    @staticmethod
    def _media(e):
        for u in e.mimeData().urls():
            p = Path(u.toLocalFile())
            if p.suffix.lower() in MEDIA_EXT:
                return p
        return None

    def dragEnterEvent(self, e):
        if self.isEnabled() and self._media(e):
            e.acceptProposedAction()
            self._lit(True)

    def dragLeaveEvent(self, _e):
        self._lit(False)

    def dropEvent(self, e):
        self._lit(False)
        p = self._media(e)
        if p:
            self.picked.emit(p)


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("root")
        self.setWindowTitle(APP)
        self.setAcceptDrops(True)
        self.settings = QSettings("local", "Lectures")
        g = self.settings.value("geometry")
        if g is not None:
            self.restoreGeometry(g)
        else:
            self.resize(1120, 780)
        self.setStyleSheet(themed(STYLE + EXTRA))
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda _s: self.apply_theme())
        self.source = None
        self.worker = None
        self.result = None
        self._alive = []                # потоки живут здесь до конца run()
        self._downloading = {}          # репозиторий -> поток загрузки

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Horizontal)
        outer.addWidget(split)

        # feedInner — прозрачный: QScrollArea включает вложенному виджету
        # заливку системным цветом, и панель светлела бы на фоне окна.
        left = QWidget(); left.setObjectName("feedInner")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(24, 20, 10, 20)
        lv.setSpacing(0)

        s = QLabel(t("Запись")); s.setObjectName("section")
        lv.addWidget(s); lv.addSpacing(8)
        self.drop = Drop()
        self.drop.picked.connect(self.set_file)
        self.drop.pick.clicked.connect(self.choose)
        lv.addWidget(self.drop)
        lv.addSpacing(20)

        s2 = QLabel(t("Что нужно")); s2.setObjectName("section")
        lv.addWidget(s2); lv.addSpacing(8)
        card = QFrame(); card.setObjectName("card")
        cl = QVBoxLayout(card); cl.setContentsMargins(16, 14, 16, 14); cl.setSpacing(13)
        # Предустановка — название и папка разом, например на каждый предмет.
        r = QHBoxLayout()
        self.preset_cap = QLabel(t("Предустановка"))
        r.addWidget(self.preset_cap); r.addStretch()
        # Кнопка с меню, а не выпадающий список: системный список рисуется
        # по-своему и не похож на остальное окно.
        self.preset = QPushButton(); self.preset.setObjectName("field")
        self.preset.setFixedSize(FIELD, 28)
        self.preset.setCursor(Qt.PointingHandCursor)
        self.preset_menu = QMenu(self.preset)
        # Иначе за скруглением остаётся квадратный угол системной подложки.
        self.preset_menu.setAttribute(Qt.WA_TranslucentBackground)
        self.preset_menu.setWindowFlags(self.preset_menu.windowFlags()
                                        | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.preset.clicked.connect(self._show_presets)
        r.addWidget(self.preset); cl.addLayout(r)
        # Название уходит в имена файлов: «Расшифровка История — дата.md».
        r = QHBoxLayout()
        self.title_cap = QLabel(t("Название"))
        r.addWidget(self.title_cap); r.addStretch()
        self.title = QLineEdit(); self.title.setObjectName("small")
        self.title.setFixedSize(FIELD, 28)
        self.title.setAlignment(Qt.AlignCenter)
        r.addWidget(self.title); cl.addLayout(r)
        for label, attr, on in ((t("Слайды"), "slides", True),
                                (t("Конспект"), "summary", False)):
            r = QHBoxLayout()
            cap = QLabel(label)
            r.addWidget(cap); r.addStretch()
            cb = QCheckBox(); cb.setProperty("caption", cap)
            cb.setChecked(self.settings.value(attr, on, type=bool))
            cb.toggled.connect(lambda v, a=attr: self.settings.setValue(a, v))
            setattr(self, attr, cb)
            r.addWidget(cb); cl.addLayout(r)
        lv.addWidget(card)
        lv.addSpacing(20)

        act = QHBoxLayout(); act.setSpacing(8)
        self.go = QPushButton(t("Разобрать")); self.go.setObjectName("primary")
        self.go.setEnabled(False); self.go.clicked.connect(self.start)
        self.go.setFixedHeight(46)
        act.addWidget(self.go, 1)
        self.cancel = QPushButton(t("Отмена")); self.cancel.setObjectName("danger")
        self.cancel.setVisible(False); self.cancel.clicked.connect(self.stop)
        self.cancel.setFixedHeight(46); self.cancel.setFixedWidth(110)
        act.addWidget(self.cancel)
        lv.addLayout(act)

        self.progress = QWidget()
        pv = QVBoxLayout(self.progress); pv.setContentsMargins(0, 12, 0, 0); pv.setSpacing(7)
        self.stage = QLabel(" "); self.stage.setObjectName("stage")
        pv.addWidget(self.stage)
        self.bar = Bar()
        pv.addWidget(self.bar)
        self.progress.setVisible(False)
        lv.addWidget(self.progress)
        lv.addSpacing(18)

        tabs = QFrame(); tabs.setObjectName("segment")
        tl = QHBoxLayout(tabs); tl.setContentsMargins(3, 3, 3, 3); tl.setSpacing(3)
        self.tab_log = QPushButton(t("Ход работы"))
        self.tab_hist = QPushButton(t("История"))
        for b in (self.tab_log, self.tab_hist):
            b.setObjectName("seg"); b.setCheckable(True); b.setAutoExclusive(True)
            b.setCursor(Qt.PointingHandCursor); tl.addWidget(b, 1)
        self.tab_log.setChecked(True)
        self.tab_log.clicked.connect(lambda: self.bottom.setCurrentIndex(0))
        self.tab_hist.clicked.connect(self.show_history)
        lv.addWidget(tabs); lv.addSpacing(8)

        self.bottom = QStackedWidget()
        self.log = QPlainTextEdit(); self.log.setReadOnly(True)
        self.bottom.addWidget(self.log)
        self.history = QListWidget(); self.history.setObjectName("history")
        self.history.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.history.setTextElideMode(Qt.ElideRight)
        self.history.itemClicked.connect(self.open_saved)
        self.history.itemActivated.connect(self.open_saved)
        self.bottom.addWidget(self.history)
        self.settings_win = SettingsWindow(self, self._build_settings())
        # Нижняя вкладка берёт остаток высоты, а не свою желаемую: иначе
        # панель выходит чуть выше окна и сбоку висит полоса прокрутки.
        for w in (self.bottom, self.log, self.history):
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.bottom.setMinimumHeight(140)
        lv.addWidget(self.bottom, 1)
        # Настройки — внизу колонки, как в Severance: одно место во всех приложениях.
        self.gear = QPushButton(t("Настройки")); self.gear.setObjectName("settings")
        self.gear.setIcon(_icon_gear(16)); self.gear.setIconSize(QSize(16, 16))
        self.gear.setCursor(Qt.PointingHandCursor)
        self.gear.clicked.connect(self.show_settings)
        gear_row = QHBoxLayout(); gear_row.addWidget(self.gear); gear_row.addStretch()
        lv.addSpacing(10); lv.addLayout(gear_row)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(10, 20, 24, 20)
        rv.setSpacing(0)

        head = QHBoxLayout(); head.setSpacing(8)
        self.toggle = QPushButton(); self.toggle.setObjectName("iconbtn")
        self.toggle.setIcon(_icon_sidebar(18)); self.toggle.setIconSize(QSize(18, 18))
        self.toggle.setFixedSize(30, 30); self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.setToolTip(t("Свернуть или показать левую панель"))
        self.toggle.clicked.connect(self.toggle_sidebar)
        head.addWidget(self.toggle)
        self.views = QFrame(); self.views.setObjectName("segment")
        vl = QHBoxLayout(self.views); vl.setContentsMargins(3, 3, 3, 3); vl.setSpacing(3)
        self.tab_text = QPushButton(t("Расшифровка"))
        self.tab_slides = QPushButton(t("Слайды"))
        for n, b in enumerate((self.tab_text, self.tab_slides)):
            b.setObjectName("seg"); b.setCheckable(True); b.setAutoExclusive(True)
            b.setCursor(Qt.PointingHandCursor); vl.addWidget(b)
            b.clicked.connect(lambda _=False, i=n: self.view.setCurrentIndex(i))
        self.tab_text.setChecked(True)
        self.views.setVisible(False)
        head.addWidget(self.views)
        head.addStretch()
        self.reveal = QPushButton(t("Показать в Finder")); self.reveal.setVisible(False)
        self.reveal.clicked.connect(self.reveal_result)
        head.addWidget(self.reveal)
        self.copy = QPushButton(t("Скопировать")); self.copy.setVisible(False)
        self.copy.clicked.connect(self.copy_result)
        head.addWidget(self.copy)
        rv.addLayout(head); rv.addSpacing(8)

        panel = QFrame(); panel.setObjectName("panel")
        pl = QVBoxLayout(panel); pl.setContentsMargins(18, 14, 8, 14)
        self.view = QStackedWidget()
        self.text = QTextBrowser()
        self.text.setOpenLinks(False)
        self.text.anchorClicked.connect(open_link)
        self.view.addWidget(self.text)
        self.gallery = QListWidget(); self.gallery.setObjectName("slides")
        self.gallery.setViewMode(QListView.IconMode)
        self.gallery.setResizeMode(QListView.Adjust)
        self.gallery.setMovement(QListView.Static)
        self.gallery.setIconSize(QSize(260, 180))
        self.gallery.setSpacing(8)
        self.gallery.setWordWrap(True)
        self.gallery.itemActivated.connect(self._open_slide)
        self.gallery.itemDoubleClicked.connect(self._open_slide)
        self.view.addWidget(self.gallery)
        pl.addWidget(self.view)
        rv.addWidget(panel, 1)
        self.right = right

        # Левая панель в прокрутке: на экране ноутбука ей бывает тесно.
        scroll = QScrollArea(); scroll.setObjectName("feed")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(left)
        self.left_panel = scroll
        split.addWidget(scroll); split.addWidget(right)
        split.setStretchFactor(0, 0); split.setStretchFactor(1, 1)
        split.setSizes([400, 720])
        split.setCollapsible(0, False); split.setCollapsible(1, False)
        self.left = left
        self._fit_min_width()
        self.setMinimumHeight(560)
        self._fill_presets()
        self._build_menu()
        for area in self.findChildren(QScrollArea):
            if area.objectName() == "feed" and area.widget() is not None:
                FitWidth(area)

    # ---- служебное
    def _keep(self, worker):
        """Ссылка на поток нужна до конца run(). Если она пропадёт раньше,
        Qt уронит приложение прямо из деструктора QThread."""
        self._alive.append(worker)
        worker.finished.connect(lambda w=worker: self._alive.remove(w))
        return worker

    def base_dir(self):
        """Общая папка — туда идёт всё без предустановки."""
        return Path(self.settings.value("out_dir", str(OUT_DIR)))

    def out_dir(self):
        chosen = self._current_preset()
        return Path(chosen["folder"]) if chosen else self.base_dir()

    # ---- предустановки
    def _presets(self):
        try:
            got = json.loads(self.settings.value("presets", "[]"))
            return [x for x in got if x.get("name") and x.get("folder")]
        except (TypeError, ValueError):
            return []

    def _save_presets(self, items):
        self.settings.setValue("presets", json.dumps(items, ensure_ascii=False))

    def _current_preset(self):
        name = self.settings.value("preset", "")
        return next((x for x in self._presets() if x["name"] == name), None)

    def _fill_presets(self):
        """Список в окне и в настройках — заново из сохранённого."""
        items = self._presets()
        chosen = self._current_preset()
        self._show_preset_name(chosen["name"] if chosen else "")
        self.preset_menu.clear()
        for name in ["", *(x["name"] for x in items)]:
            act = self.preset_menu.addAction(name or t("Нет"))
            act.triggered.connect(lambda _=False, n=name: self._on_preset(n))
        self.preset_menu.addSeparator()
        self.preset_menu.addAction(t("Новая…")).triggered.connect(
            lambda: self._add_preset(select=True))
        self.preset_list.clear()
        home = str(Path.home())
        for x in items:
            self.preset_list.addItem(f"{x['name']} — {x['folder'].replace(home, '~')}")

    def _show_preset_name(self, name):
        """Длинное имя — с многоточием в конце, а не срезанное с обоих краёв."""
        text = name or t("Нет")
        room = self.preset.width() - 22
        self.preset.setText(self.preset.fontMetrics().elidedText(text, Qt.ElideRight, room))
        self.preset.setToolTip(name if self.preset.text() != text else "")

    def _show_presets(self):
        # Меню — ровно под кнопкой и не уже её.
        self.preset_menu.setMinimumWidth(self.preset.width())
        self.preset_menu.exec(self.preset.mapToGlobal(self.preset.rect().bottomLeft()))

    def _on_preset(self, name):
        before = self._current_preset()
        self.settings.setValue("preset", name)
        self._show_preset_name(name)
        # Название подставляется из предустановки; своё, набранное руками,
        # при снятии предустановки не трогаем.
        if name:
            self.title.setText(name)
            self.title.setCursorPosition(0)       # начало названия, а не хвост
        elif before and self.title.text() == before["name"]:
            self.title.clear()
        if self.bottom.currentIndex() == 1:
            self._fill_history()

    def _add_preset(self, select=False):
        """Одно окно: название и папка. Готовая предустановка сразу в списке,
        а из меню в окне — ещё и выбрана."""
        got = PresetDialog(self, self.base_dir()).ask()
        if not got:
            return
        name, folder = got
        items = [x for x in self._presets() if x["name"] != name]
        items.append({"name": name, "folder": folder})
        self._save_presets(items)
        self._fill_presets()
        if select:
            self._on_preset(name)

    def _drop_preset(self):
        row = self.preset_list.currentRow()
        items = self._presets()
        if not 0 <= row < len(items):
            return
        if items[row]["name"] == self.settings.value("preset", ""):
            self.settings.setValue("preset", "")
        del items[row]
        self._save_presets(items)
        self._fill_presets()

    def _card(self, box, name, role):
        card = QFrame(); card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 11, 14, 11); cl.setSpacing(2)
        top = QHBoxLayout(); top.setSpacing(8)
        title = QLabel(name); title.setObjectName("cardName")
        state = QLabel(); state.setObjectName("dim")
        state.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(title); top.addStretch(); top.addWidget(state)
        cl.addLayout(top)
        sub = QLabel(role); sub.setObjectName("dim")
        sub.setWordWrap(True)
        cl.addWidget(sub)
        box.addWidget(card)
        return card, cl, state, sub

    def _support_card(self, box):
        """Поддержать: ссылки и кошелёк кнопками; «USDT TRC-20» копирует адрес."""
        import support
        _, cl, _, sub = self._card(box, t("Поддержать"), "")
        sub.setVisible(False)
        self._card_buttons(cl, *support.link_buttons(t("Скопировано")))

    def _card_buttons(self, cl, *buttons):
        row = QHBoxLayout(); row.setSpacing(8)
        row.addStretch()
        for b in buttons:
            b.setCursor(Qt.PointingHandCursor)
            row.addWidget(b)
        cl.addSpacing(6); cl.addLayout(row)

    def _build_settings(self):
        page = QScrollArea(); page.setObjectName("feed")
        page.setWidgetResizable(True)
        page.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget(); inner.setObjectName("feedInner")
        box = QVBoxLayout(inner)
        box.setContentsMargins(2, 2, 2, 2); box.setSpacing(8)

        def section(text):
            # Разделы — как «Запись» и «Что нужно» в главном окне.
            if box.count():
                box.addSpacing(12)
            lab = QLabel(t(text)); lab.setObjectName("section")
            box.addWidget(lab)

        section("Лекции")
        _, cl, self.folder_path, _ = self._card(box, t("Папка для лекций"),
                                                t("Если не выбрана предустановка"))
        pick = QPushButton(t("Выбрать…")); pick.setObjectName("cardbtn")
        pick.clicked.connect(self._choose_folder)
        show = QPushButton(t("Открыть")); show.setObjectName("cardbtn")
        show.clicked.connect(lambda: self._open_folder(self.base_dir()))
        self._card_buttons(cl, pick, show)

        _, cl, _, sub = self._card(box, t("Предустановки"), "")
        sub.setVisible(False)
        self.preset_list = QListWidget(); self.preset_list.setObjectName("history")
        self.preset_list.setFixedHeight(96)
        self.preset_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.preset_list.setTextElideMode(Qt.ElideMiddle)
        cl.addSpacing(6); cl.addWidget(self.preset_list)
        add = QPushButton(t("Добавить…")); add.setObjectName("cardbtn")
        add.clicked.connect(self._add_preset)
        drop = QPushButton(t("Удалить")); drop.setObjectName("cardbtn")
        drop.clicked.connect(self._drop_preset)
        self._card_buttons(cl, drop, add)

        section("Модели")
        self.model_rows = {}
        # Куда качать — одна настройка на все приложения (models_home).
        _, cl, self.place_state, _ = self._card(box, t("Папка для моделей"),
                                                t("Куда ставятся новые модели"))
        self.place_inside = QPushButton(t("Сбросить")); self.place_inside.setObjectName("cardbtn")
        self.place_inside.clicked.connect(lambda: self._set_models_folder(None))
        self.place_pick = QPushButton(t("Выбрать папку…")); self.place_pick.setObjectName("cardbtn")
        self.place_pick.clicked.connect(self._pick_models_folder)
        self._card_buttons(cl, self.place_inside, self.place_pick)
        # Загрузку может вести и другое приложение: ход подтягиваем раз в секунду.
        self._models_timer = QTimer(self); self._models_timer.setInterval(1000)
        self._models_timer.timeout.connect(
            lambda: self.place_state.isVisible() and self._refresh_models())
        self._models_timer.start()
        for m in models_store.CATALOG:
            card, cl, state, _ = self._card(box, models_store.short_name(m["repo"]),
                                            t(m["role"]))
            bar = Bar(); bar.setVisible(False)
            cl.addSpacing(6); cl.addWidget(bar)
            use = QPushButton(t("Использовать")); use.setObjectName("cardbtn")
            use.clicked.connect(lambda _=False, r=m["repo"]: self._use_model(r))
            act = QPushButton()
            act.clicked.connect(lambda _=False, mm=m: self._model_action(mm))
            self._card_buttons(cl, use, act)
            self.model_rows[m["repo"]] = {"state": state, "act": act, "use": use,
                                          "bar": bar, "meta": m}

        section("Приложение")
        _, cl, _, _ = self._card(box, t("Язык"), t("Язык интерфейса и конспекта"))
        self.lang_btns = []
        row = QHBoxLayout(); row.setSpacing(8); row.addStretch()
        for code, label in (("ru", "Русский"), ("en", "English")):
            b = QPushButton(label)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, c=code: self._set_lang(c))
            row.addWidget(b); self.lang_btns.append(b)
        cl.addSpacing(6); cl.addLayout(row)
        self._paint_lang()

        _, cl, _, _ = self._card(box, t("Оформление"), t("Цвета окна"))
        self.theme_btns = []
        row = QHBoxLayout(); row.setSpacing(8); row.addStretch()
        for name, label in zip(THEMES, ("Как в системе", "Светлое", "Тёмное")):
            b = QPushButton(t(label))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, n=name: self._set_theme(n))
            row.addWidget(b); self.theme_btns.append(b)
        cl.addSpacing(6); cl.addLayout(row)
        self._paint_theme()

        box.addSpacing(12)
        self._support_card(box)
        box.addStretch(1)
        sign = QLabel(f'{APP} · {AUTHOR} · <a href="{URL}">{SITE}</a>')
        sign.setObjectName("dim")
        sign.setAlignment(Qt.AlignCenter)
        sign.setOpenExternalLinks(True)
        box.addWidget(sign)
        page.setWidget(inner)
        return page

    def _paint_lang(self):
        for b, code in zip(self.lang_btns, ("ru", "en")):
            b.setObjectName("cardbtnAccent" if code == i18n.current() else "cardbtn")
            b.setEnabled(code != i18n.current())
            b.setStyleSheet("")

    def _build_menu(self):
        """Пункт «О программе»: на macOS уходит в меню приложения."""
        bar = QMenuBar(self)
        self.about_act = QAction(tf("О программе {name}", name=APP), self)
        self.about_act.setMenuRole(QAction.AboutRole)
        self.about_act.triggered.connect(self.show_about)
        self.prefs_act = QAction(t("Настройки…"), self)
        self.prefs_act.setMenuRole(QAction.PreferencesRole)
        self.prefs_act.setShortcut(QKeySequence.Preferences)
        self.prefs_act.triggered.connect(self.show_settings)
        app_menu = bar.addMenu(APP)
        app_menu.addAction(self.about_act)
        app_menu.addAction(self.prefs_act)

    def show_about(self):
        box = QMessageBox(self)
        box.setIconPixmap(app_icon().pixmap(72, 72))
        box.setTextFormat(Qt.RichText)
        box.setText(f"<b>{APP}</b>")
        # nobr: без него строка ломается и точка-разделитель повисает.
        box.setInformativeText(f'<nobr>{AUTHOR} · <a href="{URL}">{SITE}</a></nobr>')
        box.setTextInteractionFlags(Qt.TextBrowserInteraction)
        for lab in box.findChildren(QLabel):
            lab.setOpenExternalLinks(True)
        box.addButton(t("Закрыть"), QMessageBox.AcceptRole)
        box.exec()

    def _set_theme(self, name):
        self.settings.setValue("theme", name)
        self.apply_theme()

    def _paint_theme(self):
        for b, name in zip(self.theme_btns, THEMES):
            b.setObjectName("cardbtnAccent" if name == theme() else "cardbtn")
            b.setEnabled(name != theme())
            b.setStyleSheet("")

    def apply_theme(self):
        self.setStyleSheet(themed(STYLE + EXTRA))
        if hasattr(self, "theme_btns"):
            self._paint_theme()
        for w in self.findChildren(QWidget):
            w.update()

    def _set_lang(self, code):
        if code == i18n.current():
            return
        i18n.set_current(code)
        self.retranslate()

    def retranslate(self):
        """Перевод собранного окна: ключ ищется по видимой надписи."""
        self.about_act.setText(tf("О программе {name}", name=APP))
        self.prefs_act.setText(t("Настройки…"))
        self.settings_win.setWindowTitle(t("Настройки"))
        for w in self.findChildren(QWidget):
            for get, put in ((getattr(w, "text", None), getattr(w, "setText", None)),
                             (getattr(w, "toolTip", None), getattr(w, "setToolTip", None))):
                if not (get and put):
                    continue
                try:
                    cur = get()
                except TypeError:
                    continue
                key = i18n.key_of(cur) if cur else None
                if key:
                    put(t(key))
        self._paint_lang()
        self._fill_presets()
        self._refresh_models()
        self._show_source()
        self._fit_min_width()
        if self.bottom.currentIndex() == 1:
            self._fill_history()

    def toggle_sidebar(self):
        self.left_panel.setVisible(not self.left_panel.isVisible())
        self._fit_min_width()

    # ---- настройки
    def show_settings(self):
        self._refresh_models()
        self.settings_win.show()
        self.settings_win.raise_()
        self.settings_win.activateWindow()

    def _install_place(self, anchor, repo):
        """Куда ставить модель: в папку по умолчанию или в свою. False — передумали."""
        import models_home
        menu = QMenu(self)
        default = menu.addAction(tf("В {where}", where=models_home.where(repo)))
        other = menu.addAction(t("В другую папку…"))
        chosen = menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        if chosen is default:
            return None
        if chosen is other:
            path = QFileDialog.getExistingDirectory(self, t("Папка для модели"),
                                                    str(models_home.folder() or Path.home()))
            return path or False
        return False

    def _pick_models_folder(self):
        import models_home
        start = str(models_home.folder() or Path.home())
        path = QFileDialog.getExistingDirectory(self, t("Папка для моделей"), start)
        if path:
            self._set_models_folder(path)

    def _set_models_folder(self, path):
        import models_home
        models_home.set_folder(path)
        self._refresh_models()

    def _refresh_place(self):
        import models_home
        base = models_home.folder()
        off = "" if base is None or models_home.mounted(base) else t(" — недоступна")
        self.place_state.setText(models_home.label(base) + off)
        self.place_inside.setVisible(base is not None)

    def _model_note(self, repo, ready, size):
        """Где лежит, ход загрузки, очередь; None — прежняя подпись «нет, скачать»."""
        import models_home
        st = models_home.state(repo)
        if ready:
            return models_store.human(size) + " · " + models_home.where(repo)
        if st in ("downloading", "queued"):
            return models_home.describe(repo)
        if st == "offline":
            return tf("Папка недоступна: {where}", where=models_home.where(repo))
        return None

    def _refresh_models(self):
        import models_home
        self._refresh_place()
        cur = models_store.active_llm(self.settings.value("llm_repo"))
        for repo, w in self.model_rows.items():
            if repo in self._downloading:
                continue
            m = w["meta"]
            ready = models_store.is_ready(repo, m["gb"])
            note = self._model_note(repo, ready, models_store.size_ready(repo))
            w["state"].setText(note or (models_store.human(models_store.size_ready(repo)) if ready
                               else tf("{gb} ГБ, установится в {where}", gb=f"{m['gb']:g}",
                                       where=models_home.where(repo))))
            w["act"].setText(t("Удалить") if ready else t("Скачать"))
            w["act"].setObjectName("cardbtn" if ready else "cardbtnAccent")
            w["act"].setStyleSheet("")
            w["use"].setVisible(m["kind"] == "llm" and ready)
            w["use"].setEnabled(repo != cur)
            w["use"].setText(t("Используется") if repo == cur else t("Использовать"))
        self.folder_path.setText(str(self.base_dir()).replace(str(Path.home()), "~"))

    def _use_model(self, repo):
        self.settings.setValue("llm_repo", repo)
        self._refresh_models()

    def _model_action(self, m):
        if m["repo"] in self._downloading:
            self._downloading[m["repo"]].stop()
            return
        if models_store.is_ready(m["repo"], m["gb"]):
            box = QMessageBox(self)
            box.setIcon(QMessageBox.NoIcon)
            box.setWindowTitle(t("Удаление модели"))
            box.setText(tf("Удалить {name} с диска?", name=models_store.short_name(m["repo"])))
            ok = box.addButton(t("Удалить"), QMessageBox.DestructiveRole)
            box.setDefaultButton(box.addButton(t("Отмена"), QMessageBox.RejectRole))
            box.exec()
            if box.clickedButton() is ok:
                models_store.delete(m["repo"])
                self._refresh_models()
            return
        self._download(m)

    def _download(self, m):
        w = self.model_rows[m["repo"]]
        where = self._install_place(w["act"], m["repo"])
        if where is False:
            return
        w["act"].setText(t("Отмена")); w["act"].setObjectName("cardbtn")
        w["act"].setStyleSheet("")
        w["use"].setVisible(False)
        w["bar"].setVisible(True); w["bar"].set_progress(0, 1)
        dl = self._keep(DownloadWorker(m["repo"], where))
        self._downloading[m["repo"]] = dl
        dl.progress.connect(
            lambda a, b, ww=w: (ww["bar"].set_progress(a, b),
                                ww["state"].setText(tf("{a} из {gb} ГБ",
                                                       a=models_store.human(a),
                                                       gb=f"{m['gb']:g}"))))
        dl.done.connect(lambda ok, msg, ww=w: self._download_done(ww, ok, msg))
        dl.start()

    def _download_done(self, w, ok, msg):
        self._downloading.pop(w["meta"]["repo"], None)
        w["bar"].setVisible(False)
        self._refresh_models()
        if msg:
            QMessageBox.warning(self, t("Не скачалось"), msg)

    def _choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, t("Папка для расшифровок и слайдов"),
                                             str(self.base_dir()))
        if d:
            self.settings.setValue("out_dir", d)
            self._refresh_models()

    def _open_folder(self, path=None):
        target = Path(path or self.out_dir())
        target.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    # ---- запись
    # Запись можно бросить на любое место окна, не только в рамку.
    def dragEnterEvent(self, e):
        self.drop.dragEnterEvent(e)

    def dragLeaveEvent(self, e):
        self.drop.dragLeaveEvent(e)

    def dropEvent(self, e):
        self.drop.dropEvent(e)

    def choose(self):
        f, _ = QFileDialog.getOpenFileName(
            self, t("Запись лекции"), str(Path.home() / "Movies"),
            t("Видео и аудио") + " (" + " ".join(f"*{e}" for e in sorted(MEDIA_EXT)) + ")")
        if f:
            self.set_file(Path(f))

    def set_file(self, p):
        self.source = Path(p)
        self._show_source()
        self.go.setEnabled(self.worker is None)

    def _show_source(self):
        if self.source is None:
            return
        import pipeline
        self.drop.title.setText(self.source.name)
        try:
            self.drop.hint.setText(pipeline.human_stamp(pipeline.base_name(self.source)))
        except OSError:
            self.drop.hint.setText("")
        # Слайды ищутся только в видео.
        video = self.source.suffix.lower() not in pipeline.AUDIO_ONLY
        self.slides.setEnabled(video and self.worker is None)
        self.slides.property("caption").setEnabled(video)

    def _busy(self, on):
        for w in (self.go, self.drop, self.slides, self.summary, self.title,
                  self.title_cap, self.preset, self.preset_cap):
            w.setEnabled(not on)
        for cb in (self.slides, self.summary):
            cb.property("caption").setEnabled(not on)
        self.cancel.setVisible(on); self.cancel.setEnabled(True)
        self.progress.setVisible(on)
        if not on:
            self.bar.set_busy(False)
            self._show_source()

    def _need(self, repos):
        """Каких моделей не хватает — тогда в настройки, скачивать."""
        missing = [r for r in repos if not models_store.ready(r)]
        if not missing:
            return True
        QMessageBox.information(
            self, t("Нужна модель"),
            tf("Сначала скачайте {name} в настройках.",
               name=", ".join(models_store.short_name(r) for r in missing)))
        self.show_settings()
        return False

    def start(self):
        if not self.source or self.worker is not None:
            return
        llm = models_store.active_llm(self.settings.value("llm_repo"))
        need = [models_store.ASR] + ([llm] if self.summary.isChecked() else [])
        if not self._need(need):
            return
        # Флажки снимаем до _busy: он их гасит, и выключенный считался бы снятым.
        with_slides = self.slides.isChecked() and self.slides.isEnabled()
        with_summary = self.summary.isChecked()
        self.log.clear()
        self.tab_log.setChecked(True); self.bottom.setCurrentIndex(0)
        self.text.clear(); self.gallery.clear()
        for w in (self.views, self.reveal, self.copy):
            w.setVisible(False)
        self._busy(True)
        self.stage.setText(" ")
        self.bar.set_busy(True)
        self.worker = self._keep(Worker(
            str(self.source), str(self.out_dir()), self.title.text(),
            own_folder=self._current_preset() is None,
            with_slides=with_slides, with_summary=with_summary, model_id=llm))
        self.worker.line.connect(self.log.appendPlainText)
        self.worker.step.connect(self.on_step)
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(self.on_failed)
        self.worker.cancelled.connect(self.on_cancelled)
        self.worker.start()

    def stop(self):
        if self.worker:
            self.worker.stop()
            self.cancel.setEnabled(False)
            self.stage.setText(t("Остановка…"))

    def on_step(self, name, cur, total):
        self.stage.setText(f"{name}…")
        if total > 1:
            self.bar.set_progress(cur, total)
        else:
            self.bar.set_busy(True)

    def _finish(self):
        self.worker = None
        self._busy(False)
        self.go.setEnabled(self.source is not None)

    def on_done(self, r):
        self._finish()
        self.show_result(r)
        if self.bottom.currentIndex() == 1:
            self._fill_history()

    def show_result(self, r):
        self.result = r
        self.text.setMarkdown(for_view(r["markdown"]))
        self.gallery.clear()
        for f in sorted(r["slides"], key=slide_order):
            pix = QPixmap(f)
            item = QListWidgetItem(
                QIcon(pix.scaled(self.gallery.iconSize(), Qt.KeepAspectRatio,
                                 Qt.SmoothTransformation)),
                slide_label(f))
            item.setData(Qt.UserRole, f)
            item.setSizeHint(QSize(self.gallery.iconSize().width() + 20,
                                   self.gallery.iconSize().height() + 40))
            self.gallery.addItem(item)
        has_slides = bool(r["slides"])
        self.views.setVisible(has_slides)
        self.tab_text.setChecked(True); self.view.setCurrentIndex(0)
        for w in (self.reveal, self.copy):
            w.setVisible(True)
        self.copy.setText(t("Скопировать"))

    def on_cancelled(self):
        self._finish()
        self.stage.setText(" ")
        self.log.appendPlainText(t("Отменено."))

    def on_failed(self, msg):
        self._finish()
        self.log.appendPlainText(msg)
        QMessageBox.warning(self, t("Не получилось"), msg.split("\n\n")[0])

    def _open_slide(self, item):
        QDesktopServices.openUrl(QUrl.fromLocalFile(item.data(Qt.UserRole)))

    def _fit_min_width(self):
        """Минимум окна — по кнопкам над результатом в самом длинном виде на
        этом языке. Жёсткие 420 точек давали разделителю сжать их, пока
        надписи не обрезались."""
        def widest(button, *texts):
            was = button.text()
            sizes = []
            for text in texts:
                button.setText(t(text))
                sizes.append(button.sizeHint().width())
            button.setText(was)
            return max(sizes)
        head = (self.toggle.width() + self.views.sizeHint().width()
                + widest(self.reveal, "Показать в Finder")
                + widest(self.copy, "Скопировать", "Скопировано")
                + 8 * 3 + 10 + 24)
        self.right.setMinimumWidth(max(420, head))
        # Свёрнутой левой панели место не нужно.
        side = 0 if self.left_panel.isHidden() else self.left.minimumSizeHint().width() + 22
        self.setMinimumWidth(side + self.right.minimumWidth() + 34)

    def reveal_result(self):
        if self.result:
            subprocess.run(["open", "-R", self.result["md_path"]])

    # ---- история
    def show_history(self):
        self._fill_history()
        self.bottom.setCurrentIndex(1)

    def _fill_history(self):
        """Разобранное — это файлы в папке: отдельного списка не ведём, иначе
        он разойдётся с тем, что человек переложил или удалил сам."""
        import pipeline
        self.history.clear()
        rows = []
        # Разборы лежат в общей папке и в папках предустановок; у каждой записи
        # своя папка, прежние — прямо в общей.
        found = []
        for folder in dict.fromkeys([self.base_dir()] + [Path(x["folder"])
                                                           for x in self._presets()]):
            if folder.exists():
                found += [*folder.glob("*.md"), *folder.glob("*/*.md")]
        for f in found:
            got = saved_name(f.name)
            if got:
                rows.append((*got, f))
        for base, title, f in sorted(rows, key=lambda x: (x[0], x[1]), reverse=True):
            # Без названия подписываем по папке: там может быть имя файла записи.
            shown = title or _folder_title(f.parent.name, base) or pipeline.h("Лекция")
            name = f"{shown} · {pipeline.human_stamp(base)}"
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, (base, title, str(f)))
            self.history.addItem(item)
        if not rows:
            empty = QListWidgetItem(t("Разобранных лекций пока нет"))
            empty.setFlags(Qt.NoItemFlags)
            self.history.addItem(empty)

    def open_saved(self, item):
        data = item.data(Qt.UserRole)
        if not data:
            return
        base, title, md = data
        md = Path(md)
        if not md.exists():
            self._fill_history()
            return
        tail = f" {title}" if title else ""
        shots = []
        for word in ("Слайды", "Slides"):
            for d in (md.parent / f"{word}{tail} — {base}",
                      md.parent / f"{base} — {word}{tail}"):
                if d.is_dir():
                    shots = sorted(str(x) for x in d.glob("*.png"))
                    break
            if shots:
                break
        pdf = md.with_suffix(".pdf")
        self.show_result({"markdown": md.read_text(encoding="utf-8"),
                          "md_path": str(md), "slides": shots,
                          "pdf_path": str(pdf) if pdf.exists() else ""})

    def copy_result(self):
        if self.result:
            QApplication.clipboard().setText(for_reading(self.result["markdown"]))
            self.copy.setText(t("Скопировано"))
            QTimer.singleShot(1500, lambda: self.copy.setText(t("Скопировать")))

    def closeEvent(self, e):
        # Поток с моделью прервать нечем: MLX считает внутри C++. Если после
        # ожидания кто-то жив, выходим сразу — иначе Qt при разборке упадёт
        # на живом потоке, и macOS покажет отчёт о падении.
        for w in list(self._alive):
            if hasattr(w, "stop"):
                w.stop()
            w.requestInterruption()
        deadline = time.monotonic() + 3
        for w in list(self._alive):
            w.wait(max(0, int((deadline - time.monotonic()) * 1000)))
        self.settings.setValue("geometry", self.saveGeometry())
        alive = any(w.isRunning() for w in self._alive)
        super().closeEvent(e)
        if alive:
            os._exit(0)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP)
    app.setApplicationDisplayName(APP)
    w = Window(); w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
