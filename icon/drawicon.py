"""Иконка: доска с презентацией на жёлтом.

Рисуем в край — macOS обрежет по своей маске. Всё на сетке с шагом 16,
поэтому фигура читается и в 32 точки, и в 1024.
"""
import sys
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QGuiApplication, QImage, QLinearGradient,
                           QPainter, QPainterPath, QPen)

S = 1024
U = 16
TOP, LOW = QColor("#f8da88"), QColor("#e8bb4f")
BOARD, LINE, ACCENT = QColor("#f4f6fa"), QColor("#aab4c4"), QColor("#cf9f35")


def rounded(rect, radius):
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def draw(path, layer=False):
    """layer=True — только доска на прозрачном фоне: подложку и тень macOS
    рисует сама, по своим правилам для светлой и тёмной темы."""
    QGuiApplication.instance() or QGuiApplication([])
    img = QImage(S, S, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)

    if not layer:
        back = QLinearGradient(0, 0, 0, S)
        back.setColorAt(0.0, TOP)
        back.setColorAt(1.0, LOW)
        p.fillRect(QRectF(0, 0, S, S), QBrush(back))

    board = QRectF(10 * U, 13 * U, 44 * U, 30 * U)
    radius = 3 * U

    # Ножка и основание — под доской, белые.
    p.setPen(QPen(BOARD, 3 * U, Qt.SolidLine, Qt.RoundCap))
    mid = board.center().x()
    p.drawLine(QPointF(mid, board.bottom()), QPointF(mid, board.bottom() + 8 * U))
    p.drawLine(QPointF(mid - 8 * U, board.bottom() + 8 * U),
               QPointF(mid + 8 * U, board.bottom() + 8 * U))

    if not layer:
        p.setPen(Qt.NoPen)
        for step in range(1, 7):
            p.setBrush(QColor(0, 0, 0, 14))
            p.drawPath(rounded(board.adjusted(-step * 2, step * 3, step * 2, step * 4),
                               radius + step * 2))

    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(BOARD))
    p.drawPath(rounded(board, radius))

    # Заголовок слайда цветом акцента и три строки под ним.
    left = board.left() + 6 * U
    p.setPen(QPen(ACCENT, 3 * U, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(left, board.top() + 8 * U), QPointF(left + 18 * U, board.top() + 8 * U))
    p.setPen(QPen(LINE, 2 * U, Qt.SolidLine, Qt.RoundCap))
    for n, width in enumerate((30, 30, 20)):
        y = board.top() + 15 * U + n * 5 * U
        p.drawLine(QPointF(left, y), QPointF(left + width * U, y))
    p.end()
    img.save(path)


if __name__ == "__main__":
    draw(sys.argv[1] if len(sys.argv) > 1 else "icon/AppIcon-1024.png",
         len(sys.argv) > 2 and sys.argv[2] == "layer")
