"""Centralized design system, palette, typography, and QSS for Karaoke Subtitle Engine."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPalette, QPen
from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle, QWidget

# Surface hierarchy (deep obsidian -> elevated slate -> raised controls)
BG_APP = "#0D1017"
BG_HEADER = "#111621"
BG_SIDEBAR = "#121722"
BG_SURFACE = "#161C28"
BG_SURFACE_ALT = "#1C2332"
BG_INPUT = "#0F131C"
BG_STAGE = "#080A0F"

# Borders
BORDER_SUBTLE = "#222A3A"
BORDER_CONTROL = "#2E384D"
BORDER_HOVER = "#495A7A"

# Text hierarchy
TEXT_PRIMARY = "#EEF2F9"
TEXT_SECONDARY = "#9CA7BE"
TEXT_MUTED = "#6C778E"

# Studio accent (warm amber-gold)
ACCENT = "#F5B841"
ACCENT_HOVER = "#FFCA5E"
ACCENT_PRESSED = "#D99D2A"
ACCENT_INK = "#161208"
ACCENT_SOFT = "#261F13"

# Semantic status
SUCCESS = "#38C985"
SUCCESS_SOFT = "#11281F"
WARNING = "#F0A83C"
WARNING_SOFT = "#2B2112"
ERROR = "#F06464"
ERROR_SOFT = "#2B1518"


class StudioProxyStyle(QProxyStyle):
    """Fusion proxy style that renders crisp vector checkboxes matching the dark studio palette."""

    def __init__(self) -> None:
        super().__init__("Fusion")

    def drawPrimitive(self, element, option, painter, widget=None) -> None:
        if element == QStyle.PrimitiveElement.PE_IndicatorCheckBox:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = QRectF(option.rect).adjusted(1.5, 1.5, -1.5, -1.5)
            enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
            checked = bool(option.state & QStyle.StateFlag.State_On)
            hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

            if checked:
                fill = QColor(ACCENT if enabled else "#4B3F26")
                border = QColor(ACCENT_HOVER if (enabled and hovered) else fill)
            else:
                fill = QColor(BG_INPUT if enabled else BG_SIDEBAR)
                border = QColor(BORDER_HOVER if (enabled and hovered) else (BORDER_HOVER if enabled else "#232B3B"))

            painter.setBrush(fill)
            painter.setPen(QPen(border, 1.3))
            painter.drawRoundedRect(rect, 4.0, 4.0)

            if checked:
                check_pen = QPen(QColor(ACCENT_INK if enabled else "#8C7D60"), 2.0)
                check_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                check_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(check_pen)
                x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
                painter.drawLine(QPointF(x + w * 0.24, y + h * 0.53), QPointF(x + w * 0.43, y + h * 0.72))
                painter.drawLine(QPointF(x + w * 0.43, y + h * 0.72), QPointF(x + w * 0.77, y + h * 0.30))

            painter.restore()
            return
        super().drawPrimitive(element, option, painter, widget)


def preferred_ui_font() -> str:
    families = set(QFontDatabase.families())
    for candidate in ("Segoe UI Variable Text", "Segoe UI", "Noto Sans"):
        if candidate in families:
            return candidate
    return QFont().defaultFamily()


def build_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG_APP))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Base, QColor(BG_INPUT))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(BG_SURFACE))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(BG_SURFACE_ALT))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Button, QColor(BG_SURFACE_ALT))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Light, QColor(BORDER_HOVER))
    palette.setColor(QPalette.ColorRole.Midlight, QColor(BORDER_CONTROL))
    palette.setColor(QPalette.ColorRole.Mid, QColor(BORDER_CONTROL))
    palette.setColor(QPalette.ColorRole.Dark, QColor(BORDER_SUBTLE))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(ACCENT_INK))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_MUTED))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(TEXT_MUTED))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(TEXT_MUTED))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(TEXT_MUTED))
    return palette


THEME_QSS = f"""
QMainWindow, QDialog, QMessageBox, QInputDialog {{
    background-color: {BG_APP};
    color: {TEXT_PRIMARY};
}}
QWidget {{
    color: {TEXT_PRIMARY};
    font-size: 13px;
}}
QLabel {{
    background: transparent;
}}
QLabel[role="title"] {{
    font-size: 18px;
    font-weight: 700;
    color: {TEXT_PRIMARY};
}}
QLabel[role="subtitle"] {{
    font-size: 12px;
    color: {TEXT_SECONDARY};
}}
QLabel[role="section"] {{
    font-size: 14px;
    font-weight: 700;
    color: {TEXT_PRIMARY};
}}
QLabel[role="eyebrow"] {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.6px;
    color: {TEXT_MUTED};
}}
QLabel[role="field"] {{
    font-size: 12px;
    font-weight: 600;
    color: {TEXT_SECONDARY};
}}
QLabel[role="muted"] {{
    font-size: 12px;
    color: {TEXT_SECONDARY};
}}
QLabel[role="hint"] {{
    font-size: 12px;
    color: {TEXT_MUTED};
}}
QLabel[role="mono"] {{
    font-size: 12px;
    color: {TEXT_SECONDARY};
}}
QLabel[tone="success"] {{
    color: {SUCCESS};
}}
QLabel[tone="warning"] {{
    color: {WARNING};
}}
QLabel[tone="error"] {{
    color: {ERROR};
}}

QFrame#header_bar {{
    background-color: {BG_HEADER};
    border: none;
    border-bottom: 1px solid {BORDER_SUBTLE};
}}
QFrame#footer_bar {{
    background-color: {BG_HEADER};
    border: none;
    border-top: 1px solid {BORDER_SUBTLE};
}}
QFrame#sidebar_panel {{
    background-color: {BG_SIDEBAR};
    border: none;
    border-right: 1px solid {BORDER_SUBTLE};
}}
QFrame#inspector_panel {{
    background-color: {BG_SIDEBAR};
    border: none;
    border-left: 1px solid {BORDER_SUBTLE};
}}
QFrame#card, QFrame#section_card {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 10px;
}}
QFrame#sub_panel {{
    background-color: {BG_SIDEBAR};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 8px;
}}
QFrame#media_slot {{
    background-color: {BG_HEADER};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 8px;
}}
QFrame#media_slot[populated="true"] {{
    background-color: #131926;
    border-color: #313E57;
}}
QFrame#stage_frame {{
    background-color: {BG_STAGE};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 10px;
}}
QFrame#notice_bar {{
    background-color: {WARNING_SOFT};
    border: 1px solid #63491E;
    border-radius: 8px;
}}
QFrame#collapsible_section {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 8px;
}}
QFrame#preset_card {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 8px;
}}
QFrame#preset_card:hover {{
    background-color: {BG_SURFACE_ALT};
    border-color: {BORDER_HOVER};
}}
QFrame#preset_card[selected="true"] {{
    background-color: #1D222D;
    border: 1.5px solid {ACCENT};
}}
QFrame#divider {{
    background-color: {BORDER_SUBTLE};
    max-height: 1px;
    min-height: 1px;
}}

QLabel#badge {{
    background-color: {BG_SURFACE_ALT};
    border: 1px solid {BORDER_CONTROL};
    border-radius: 10px;
    padding: 2px 9px;
    font-size: 11px;
    font-weight: 600;
    color: {TEXT_SECONDARY};
}}
QLabel#badge[tone="accent"] {{
    background-color: {ACCENT_SOFT};
    border-color: #7D5D20;
    color: {ACCENT};
}}
QLabel#badge[tone="success"] {{
    background-color: {SUCCESS_SOFT};
    border-color: #246E4C;
    color: {SUCCESS};
}}
QLabel#badge[tone="warning"] {{
    background-color: {WARNING_SOFT};
    border-color: #6B4D1C;
    color: {WARNING};
}}
QLabel#badge[tone="error"] {{
    background-color: {ERROR_SOFT};
    border-color: #6F2B30;
    color: {ERROR};
}}

QPlainTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER_CONTROL};
    border-radius: 6px;
    padding: 5px 9px;
    color: {TEXT_PRIMARY};
    selection-background-color: #364B73;
    selection-color: #FFFFFF;
}}
QPlainTextEdit {{
    padding: 8px 10px;
}}
QPlainTextEdit:hover, QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: {BORDER_HOVER};
}}
QPlainTextEdit:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {ACCENT};
    background-color: #111622;
}}
QPlainTextEdit:disabled, QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background-color: {BG_SIDEBAR};
    border-color: #1F2636;
    color: {TEXT_MUTED};
}}
QComboBox QAbstractItemView {{
    background-color: {BG_SURFACE_ALT};
    border: 1px solid {BORDER_CONTROL};
    selection-background-color: #2E3D59;
    selection-color: {TEXT_PRIMARY};
    outline: none;
    padding: 4px;
}}

QPushButton {{
    background-color: {BG_SURFACE_ALT};
    border: 1px solid {BORDER_CONTROL};
    border-radius: 6px;
    padding: 6px 12px;
    font-weight: 600;
    color: {TEXT_PRIMARY};
}}
QPushButton:hover {{
    background-color: #232C3F;
    border-color: {BORDER_HOVER};
}}
QPushButton:pressed {{
    background-color: #171D2A;
}}
QPushButton:focus {{
    border-color: {ACCENT};
}}
QPushButton:disabled {{
    background-color: #141923;
    border-color: #202736;
    color: {TEXT_MUTED};
}}
QPushButton#generate, QPushButton[variant="primary"] {{
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
    color: {ACCENT_INK};
    font-weight: 700;
    padding: 9px 18px;
}}
QPushButton#generate:hover, QPushButton[variant="primary"]:hover {{
    background-color: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}
QPushButton#generate:pressed, QPushButton[variant="primary"]:pressed {{
    background-color: {ACCENT_PRESSED};
    border-color: {ACCENT_PRESSED};
}}
QPushButton#generate:disabled, QPushButton[variant="primary"]:disabled {{
    background-color: #463A20;
    border-color: #463A20;
    color: #8F8267;
}}
QPushButton[variant="ghost"] {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER_SUBTLE};
    color: {TEXT_SECONDARY};
    padding: 5px 10px;
}}
QPushButton[variant="ghost"]:hover {{
    background-color: {BG_SURFACE_ALT};
    border-color: {BORDER_HOVER};
    color: {TEXT_PRIMARY};
}}
QPushButton[variant="ghost"]:checked {{
    background-color: {ACCENT_SOFT};
    border-color: #7D5D20;
    color: {ACCENT};
}}
QPushButton[variant="ghost"]:disabled {{
    background-color: #131822;
    border-color: #1D2331;
    color: {TEXT_MUTED};
}}
QPushButton[variant="danger"] {{
    background-color: {BG_SURFACE_ALT};
    border: 1px solid #442C31;
    color: #F28B8B;
}}
QPushButton[variant="danger"]:hover {{
    background-color: {ERROR_SOFT};
    border-color: {ERROR};
    color: #FFD6D6;
}}
QPushButton[variant="danger"]:disabled {{
    background-color: #141923;
    border-color: #202736;
    color: {TEXT_MUTED};
}}
QPushButton#collapse_header {{
    background-color: transparent;
    border: none;
    border-radius: 7px;
    padding: 9px 12px;
    text-align: left;
    font-size: 13px;
    font-weight: 700;
    color: {TEXT_PRIMARY};
}}
QPushButton#collapse_header:hover {{
    background-color: {BG_SURFACE_ALT};
}}
QPushButton#color_swatch {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER_CONTROL};
    border-radius: 6px;
    padding: 5px 10px 5px 34px;
    text-align: left;
    font-weight: 600;
}}
QPushButton#color_swatch:hover {{
    border-color: {BORDER_HOVER};
    background-color: #141925;
}}

QCheckBox {{
    spacing: 8px;
    background: transparent;
    color: {TEXT_PRIMARY};
}}
QCheckBox:disabled {{
    color: {TEXT_MUTED};
}}

QProgressBar {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER_CONTROL};
    border-radius: 5px;
    text-align: center;
    color: {TEXT_PRIMARY};
    font-size: 11px;
    font-weight: 700;
    min-height: 20px;
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 4px;
}}

QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #2C364A;
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: #445370;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    height: 0px;
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: #2C364A;
    border-radius: 4px;
    min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{
    background: #445370;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    width: 0px;
    background: transparent;
}}

QToolTip {{
    background-color: {BG_SURFACE_ALT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_HOVER};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}
"""


def apply_theme(target: QApplication | QWidget) -> None:
    """Apply the unified Fusion palette, readable UI font, and studio stylesheet."""
    if isinstance(target, QApplication):
        target.setStyle(StudioProxyStyle())
        font = QFont(preferred_ui_font(), 10)
        target.setFont(font)
        target.setPalette(build_palette())
        target.setStyleSheet(THEME_QSS)
    else:
        if QApplication.instance() is not None and not isinstance(QApplication.style(), StudioProxyStyle):
            target.setStyle(StudioProxyStyle())
        target.setPalette(build_palette())
        target.setStyleSheet(THEME_QSS)
