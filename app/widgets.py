"""Reusable presentation widgets for Karaoke Subtitle Engine V2."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from . import theme
from .core import EngineError
from .font_library import all_faces

_FONTS_REGISTERED = False


def ensure_bundled_fonts() -> list[str]:
    """Register bundled static TTFs once per process and return any load errors."""
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return []
    errors: list[str] = []
    for face in all_faces():
        try:
            QFontDatabase.addApplicationFont(str(face.path()))
        except EngineError as exc:
            errors.append(str(exc))
    _FONTS_REGISTERED = True
    return errors


def refresh_style(widget: QWidget) -> None:
    """Re-polish a widget after changing a dynamic QSS property."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_prop(widget: QWidget, name: str, value: object) -> None:
    widget.setProperty(name, value)
    refresh_style(widget)


def make_label(text: str = "", role: str = "", tone: str = "", wrap: bool = True) -> QLabel:
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
    if tone:
        widget.setProperty("tone", tone)
    widget.setWordWrap(wrap)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    return widget


def make_divider() -> QFrame:
    line = QFrame(objectName="divider")
    line.setFrameShape(QFrame.Shape.HLine)
    return line


class StudioMark(QWidget):
    """Minimal vector studio emblem drawn directly with QPainter."""

    def __init__(self, size: int = 34, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(1, 1, self.width() - 2, self.height() - 2)
        painter.setPen(QPen(QColor("#3C3320"), 1.2))
        painter.setBrush(QColor("#1B1914"))
        painter.drawRoundedRect(box, 8, 8)

        # Stylized equalizer / timed lyric bars
        bars = (
            (0.24, 0.42, 0.11, 0.30, "#6E7B94"),
            (0.41, 0.25, 0.11, 0.47, theme.ACCENT),
            (0.58, 0.34, 0.11, 0.38, theme.ACCENT_HOVER),
            (0.75, 0.48, 0.11, 0.24, "#9CA7BE"),
        )
        w, h = self.width(), self.height()
        painter.setPen(Qt.PenStyle.NoPen)
        for rx, ry, rw, rh, color in bars:
            painter.setBrush(QColor(color))
            rect = QRectF(w * rx - (w * rw) / 2, h * ry, w * rw, h * rh)
            painter.drawRoundedRect(rect, 2.0, 2.0)

        # Subtle subtitle underline bar at bottom
        painter.setBrush(QColor(theme.ACCENT))
        painter.drawRoundedRect(QRectF(w * 0.20, h * 0.78, w * 0.60, h * 0.08), 1.5, 1.5)


class StatusBadge(QLabel):
    """Compact pill badge for preset status, media state, and font capability tags."""

    def __init__(self, text: str = "", tone: str = "neutral", parent: QWidget | None = None) -> None:
        super().__init__(text, parent, objectName="badge")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        set_prop(self, "tone", tone)


class SectionCard(QFrame):
    """Consistent elevated workspace card with header title and optional trailing widget."""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        header_widget: QWidget | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, objectName="section_card")
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(16, 14, 16, 16)
        self.root_layout.setSpacing(12)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(2)
        self.title_label = make_label(title, role="section")
        titles.addWidget(self.title_label)
        self.subtitle_label = make_label(subtitle, role="hint") if subtitle else None
        if self.subtitle_label is not None:
            titles.addWidget(self.subtitle_label)
        header.addLayout(titles, 1)
        if header_widget is not None:
            header.addWidget(header_widget)
        self.root_layout.addLayout(header)

        self.body_layout = QVBoxLayout()
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(10)
        self.root_layout.addLayout(self.body_layout)


class CollapsibleSection(QFrame):
    """Inspector section with a clickable header bar and collapsible body."""

    def __init__(self, title: str, expanded: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent, objectName="collapsible_section")
        self._title = title
        self._expanded = expanded

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header_btn = QPushButton(objectName="collapse_header")
        self.header_btn.setCheckable(True)
        self.header_btn.setChecked(expanded)
        self.header_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header_btn.clicked.connect(self.set_expanded)
        outer.addWidget(self.header_btn)

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(12, 2, 12, 12)
        self.content_layout.setSpacing(9)
        outer.addWidget(self.content)

        self.set_expanded(expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self.header_btn.setChecked(self._expanded)
        arrow = "▾" if self._expanded else "▸"
        self.header_btn.setText(f"{arrow}  {self._title}")
        self.content.setVisible(self._expanded)


class ColorSwatchButton(QPushButton):
    """Color selector button displaying an inline painted swatch and hex value."""

    def __init__(self, color_hex: str = "#FFFFFF", text: str = "#FFFFFF", parent: QWidget | None = None) -> None:
        super().__init__(text, parent, objectName="color_swatch")
        self._swatch = QColor(color_hex)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(32)

    def set_swatch(self, color_hex: str, label: str) -> None:
        self._swatch = QColor(color_hex)
        self.setText(label)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = 16
        x = 10.0
        y = (self.height() - size) / 2.0
        rect = QRectF(x, y, size, size)
        fill = QColor(self._swatch)
        if not self.isEnabled():
            fill.setAlpha(110)
        painter.setBrush(fill)
        border_color = QColor("#6C7A96") if fill.lightness() < 90 else QColor("#2D3546")
        painter.setPen(QPen(border_color, 1.0))
        painter.drawRoundedRect(rect, 4.0, 4.0)


class FontComboBox(QComboBox):
    """Family dropdown that previews bundled typefaces using Qt's FontRole when registered."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._registered = set(QFontDatabase.families())
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(10)

    def add_family(self, family: str) -> None:
        self.addItem(family, family)
        if family in self._registered:
            index = self.count() - 1
            font = QFont(family, 10)
            self.setItemData(index, font, Qt.ItemDataRole.FontRole)


class PresetCard(QFrame):
    """Selectable card representing a built-in or custom look in Creative Subtitle Studio."""

    clicked = Signal(str)

    def __init__(
        self,
        name: str,
        subtitle: str,
        style,
        is_builtin: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, objectName="preset_card")
        self.preset_name = name
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("selected", False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(5)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        self.name_label = make_label(name, role="field")
        self.name_label.setStyleSheet("font-size: 13px; font-weight: 700; color: #EEF2F9;")
        top.addWidget(self.name_label, 1)
        tag = StatusBadge("Built-in" if is_builtin else "Custom", "neutral")
        top.addWidget(tag)
        layout.addLayout(top)

        self.desc_label = make_label(subtitle, role="hint")
        self.desc_label.setStyleSheet("font-size: 11px; color: #8B97AF;")
        layout.addWidget(self.desc_label)

        # Mini specimen strip reflecting the preset's palette and treatment
        strip = QFrame()
        strip.setFixedHeight(26)
        bg_color = style.box_color if style.background else "#0B0E15"
        strip.setStyleSheet(
            f"background-color: {bg_color}; border: 1px solid #252E40; border-radius: 5px;"
        )
        strip_layout = QHBoxLayout(strip)
        strip_layout.setContentsMargins(8, 2, 8, 2)
        strip_layout.setSpacing(6)

        hi_hex = style.hi_color or style.normal
        en_hex = style.en_color or style.normal
        active_hex = style.active if style.karaoke else en_hex

        hi_sample = QLabel("शब्द")
        hi_font = QFont(style.hindi_font, 10)
        hi_font.setWeight(QFont.Weight.Bold)
        hi_sample.setFont(hi_font)
        hi_sample.setStyleSheet(f"color: {hi_hex}; background: transparent;")
        en_sample = QLabel("Word")
        en_font = QFont(style.font, 10)
        en_font.setWeight(QFont.Weight.Bold)
        en_font.setItalic(bool(style.en_italic))
        en_sample.setFont(en_font)
        en_sample.setStyleSheet(f"color: {active_hex}; background: transparent;")
        strip_layout.addWidget(hi_sample)
        strip_layout.addWidget(en_sample)
        strip_layout.addStretch(1)

        dots = QHBoxLayout()
        dots.setSpacing(4)
        for hex_color in (style.normal, style.active if style.karaoke else (style.en_color or style.normal),
                          style.outline if style.outline_enabled else style.shadow_color):
            dot = QLabel()
            dot.setFixedSize(8, 8)
            dot.setStyleSheet(
                f"background-color: {hex_color}; border: 1px solid #4A566E; border-radius: 4px;"
            )
            dots.addWidget(dot)
        strip_layout.addLayout(dots)
        layout.addWidget(strip)

    def set_selected(self, selected: bool) -> None:
        set_prop(self, "selected", selected)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.preset_name)
        super().mousePressEvent(event)


class StyleSummaryStrip(QFrame):
    """Compact summary card in MainWindow showing the active Creative Subtitle Studio look."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, objectName="sub_panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        self.preset_badge = StatusBadge("Karaoke Highlight", "accent")
        self.mode_label = make_label("", role="hint")
        top.addWidget(self.preset_badge)
        top.addWidget(self.mode_label, 1)
        layout.addLayout(top)

        self.fonts_label = make_label("", role="muted")
        layout.addWidget(self.fonts_label)

        self.swatches_row = QHBoxLayout()
        self.swatches_row.setContentsMargins(0, 2, 0, 0)
        self.swatches_row.setSpacing(10)
        self._swatch_items: list[tuple[QLabel, QLabel]] = []
        for label_text in ("Base", "Active", "Done", "Outline"):
            pair = QHBoxLayout()
            pair.setSpacing(5)
            dot = QLabel()
            dot.setFixedSize(11, 11)
            caption = make_label(label_text, role="hint")
            caption.setStyleSheet("font-size: 11px; color: #8B97AF;")
            pair.addWidget(dot)
            pair.addWidget(caption)
            self.swatches_row.addLayout(pair)
            self._swatch_items.append((dot, caption))
        self.swatches_row.addStretch(1)
        layout.addLayout(self.swatches_row)

    def update_style(self, preset_name: str, style) -> None:
        self.preset_badge.setText(preset_name)
        mode = "Timed word karaoke" if style.karaoke else "Static phrase look"
        self.mode_label.setText(f"{mode} · {style.size}px")
        self.fonts_label.setText(f"EN: {style.font}  ·  HI: {style.hindi_font}")
        colors = (
            style.normal,
            style.active if style.karaoke else (style.en_color or style.normal),
            style.completed if (style.karaoke and style.color_completed) else (style.hi_color or style.normal),
            style.outline if style.outline_enabled else style.shadow_color,
        )
        labels = (
            ("Base", "Active", "Done", "Outline")
            if style.karaoke
            else ("Base", "English", "Hindi", "Outline" if style.outline_enabled else "Shadow")
        )
        for (dot, caption), color, label_text in zip(self._swatch_items, colors, labels, strict=True):
            dot.setStyleSheet(
                f"background-color: {color}; border: 1px solid #4A566E; border-radius: 5px;"
            )
            caption.setText(label_text)
