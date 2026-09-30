"""PDF для конспекта: расшифровка, а слайды — в тех местах, где их показывали.

Один файл вместо текста и пачки картинок: так его можно отдать нейросети одним
вложением, и лимит на число файлов в сообщении не мешает.
"""
from pathlib import Path

from PySide6.QtCore import QMarginsF, QSizeF, QUrl
from PySide6.QtGui import (QFont, QPageLayout, QPageSize, QPdfWriter, QTextCursor,
                           QTextDocument)

PAGE_W = 520          # ширина набора в точках: A4 без полей по 15 мм


def make_pdf(md, base_dir, out):
    doc = QTextDocument()
    doc.setDefaultFont(QFont("Helvetica Neue", 10))
    # Картинки в разметке заданы путями от папки с расшифровкой.
    doc.setBaseUrl(QUrl.fromLocalFile(str(Path(base_dir)) + "/"))
    doc.setMarkdown(md)
    doc.setPageSize(QSizeF(PAGE_W, PAGE_W * 297 / 210))

    # Слайды приходят в исходном размере и вылезают за страницу: ужимаем
    # до ширины набора, высота — по пропорции. Сначала собираем, потом меняем:
    # правка формата перекраивает фрагменты, и обход сбивается.
    found = []
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid() and frag.charFormat().isImageFormat():
                found.append((frag.position(), frag.length(),
                              frag.charFormat().toImageFormat()))
            it += 1
        block = block.next()
    for pos, length, img in found:
        pic = doc.resource(QTextDocument.ImageResource, QUrl(img.name()))
        if pic is None or pic.isNull() or pic.width() <= 0:
            continue
        w = min(PAGE_W, pic.width())
        img.setWidth(w)
        img.setHeight(w * pic.height() / pic.width())
        cur = QTextCursor(doc)
        cur.setPosition(pos)
        cur.setPosition(pos + length, QTextCursor.KeepAnchor)
        cur.setCharFormat(img)

    writer = QPdfWriter(str(out))
    writer.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait,
                                     QMarginsF(15, 15, 15, 15), QPageLayout.Millimeter))
    writer.setTitle(Path(out).stem)
    writer.setCreator("Lectures")
    doc.print_(writer)
