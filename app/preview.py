from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .core import Style


class SubtitlePreview(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.style = Style()
        self.words = ("Every", "word", "shines")
        self.setMinimumHeight(125)
        self.setAccessibleName("Subtitle style preview")

    def show_style(self, style: Style, words: tuple[str, str, str]) -> None:
        self.style = style
        self.words = words
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor("#35435a")))
        painter.setBrush(QColor("#10141d"))
        painter.drawRoundedRect(area, 8, 8)

        style = self.style
        scale = min(0.5, self.width() / 1300)
        font = QFont(style.font)
        font.setBold(True)
        font.setPixelSize(max(10, round(style.size * scale)))
        metrics = QFontMetricsF(font)
        advance = metrics.horizontalAdvance(" ")
        widths = [metrics.horizontalAdvance(word) for word in self.words]
        width = sum(widths) + advance * 2
        margin = max(8, style.margin * scale)
        x = (margin, (self.width() - width) / 2, self.width() - margin - width)[style.horizontal - 1]
        y = (self.height() - margin - metrics.descent(),
             (self.height() + metrics.ascent() - metrics.descent()) / 2,
             margin + metrics.ascent())[style.vertical // 3]
        for word, color, word_width in zip(
                self.words, (style.completed, style.active, style.normal), widths, strict=True):
            path = QPainterPath()
            path.addText(QPointF(x, y), font, word)
            if style.shadow:
                distance = style.shadow * scale
                painter.fillPath(path.translated(distance, distance), QColor("#99000000"))
            if style.stroke:
                outline = QPen(QColor(style.outline))
                outline.setWidthF(2 * style.stroke * scale)
                outline.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.strokePath(path, outline)
            painter.fillPath(path, QColor(color))
            x += word_width + advance
