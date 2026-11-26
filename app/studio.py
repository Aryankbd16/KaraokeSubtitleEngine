"""Creative Subtitle Studio dialog. All controls edit an immutable presentation snapshot."""
from dataclasses import replace

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QInputDialog, QLabel, QMessageBox, QPushButton, QScrollArea, QSpinBox, QTabWidget,
    QVBoxLayout, QWidget,
)

from .core import EngineError
from .font_library import ENGLISH, HINDI, WEIGHTS, has_italic, weights
from .presets import BUILTINS
from .preview import FramePreview

SAMPLES = {
    "Mixed": "ज़िंदगी finds उम्मीद in every मुस्कान",
    "Hindi": "ज़िंदगी उम्मीद और विश्वास से हमेशा मुस्कुराती है।",
    "English": "Every word shines a little brighter",
}


class StudioDialog(QDialog):
    def __init__(self, store, selected, style, video, info, script, parent=None):
        super().__init__(parent)
        self.store, self.selected, self.style = store, selected, style
        self.loading = True
        self.fields = {}
        self.setWindowTitle("Creative Subtitle Studio")
        self.resize(900, 600)
        outer = QVBoxLayout(self)
        bar = QHBoxLayout()
        outer.addLayout(bar)
        self.presets = QComboBox()
        bar.addWidget(self.presets, 1)
        self.actions = {}
        for title, action in (("Save as…", "create"), ("Save", "update"), ("Rename…", "rename"),
                              ("Delete…", "delete"), ("Restore default", "restore")):
            btn = QPushButton(title)
            self.actions[action] = btn
            btn.clicked.connect(lambda checked=False, op=action: self.manage(op))
            bar.addWidget(btn)
        body = QHBoxLayout()
        outer.addLayout(body, 1)
        self.tabs = QTabWidget()
        body.addWidget(self.tabs, 1)
        form = self.tab("Type")
        for key, title, families in (("en", "English", ENGLISH), ("hi", "Hindi", HINDI)):
            family = QComboBox()
            for name in families:
                family.addItem(name, name)
            self.field(form, "font" if key == "en" else "hindi_font", title + " family", family)
            weight = QComboBox()
            self.field(form, key + "_weight", title + " weight", weight)
            self.check(form, key + "_italic", title + " italic")
        self.number(form, "size", "Font size", 16, 120)
        form = self.tab("Colors")
        self.check(form, "karaoke", "Highlight active word")
        self.check(form, "color_completed", "Recolor completed words")
        for key, title in (("normal", "Base text"), ("en_color", "English text"), ("hi_color", "Hindi text"),
                           ("active", "Active word"), ("completed", "Completed words"),
                           ("outline", "Outline"), ("shadow_color", "Shadow"), ("box_color", "Background")):
            btn = QPushButton()
            self.fields[key] = btn
            btn.clicked.connect(lambda checked=False, field=key: self.pick(field))
            if key in ("en_color", "hi_color"):
                group = QHBoxLayout()
                group.addWidget(btn, 1)
                reset = QPushButton("Use base")
                reset.clicked.connect(lambda checked=False, field=key: self.set_color(field, None))
                group.addWidget(reset)
                form.addRow(title, group)
            else:
                form.addRow(title, btn)
        form = self.tab("Effects")
        self.check(form, "outline_enabled", "Outline")
        self.number(form, "stroke", "Outline thickness", 0, 10)
        self.check(form, "shadow_enabled", "Shadow")
        self.number(form, "shadow", "Shadow distance", 0, 10)
        self.number(form, "shadow_opacity", "Shadow opacity (%)", 0, 100)
        self.check(form, "background", "Background box")
        self.number(form, "box_opacity", "Box opacity (%)", 0, 100)
        form = self.tab("Layout")
        for key, title, options in (("horizontal", "Alignment", (("Left", 1), ("Center", 2), ("Right", 3))),
                                    ("vertical", "Position", (("Bottom", 0), ("Middle", 3), ("Top", 6)))):
            combo = QComboBox()
            for name, value in options:
                combo.addItem(name, value)
            self.field(form, key, title, combo)
        self.number(form, "margin", "Edge margin", 0, 200)
        self.number(form, "line_gap", "Line spacing", 0, 100)
        self.number(form, "words_per_line", "Words per line", 1, 20)
        self.number(form, "width_percent", "Maximum width (%)", 20, 100)
        right = QVBoxLayout()
        body.addLayout(right, 1)
        self.sample = QComboBox()
        if script.strip():
            self.sample.addItem("Current script", " ".join(script.split()[:24]))
        for name, sample in SAMPLES.items():
            self.sample.addItem(name, sample)
        right.addWidget(self.sample)
        self.preview = FramePreview(video, info)
        right.addWidget(self.preview, 1)
        self.notice = QLabel(store.notice)
        self.notice.setWordWrap(True)
        outer.addWidget(self.notice)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.apply)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.refresh_names()
        self.presets.currentTextChanged.connect(self.select)
        self.sample.currentIndexChanged.connect(self.refresh_preview)
        self.load_style(style)

    def tab(self, name):
        page = QWidget()
        form = QFormLayout(page)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, name)
        return form

    def field(self, form, key, title, widget):
        self.fields[key] = widget
        form.addRow(title, widget)
        if isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(self.changed)
        elif isinstance(widget, QCheckBox):
            widget.toggled.connect(self.changed)
        else:
            widget.valueChanged.connect(self.changed)

    def check(self, form, key, title):
        self.field(form, key, title, QCheckBox())

    def number(self, form, key, title, low, high):
        widget = QSpinBox()
        widget.setRange(low, high)
        self.field(form, key, title, widget)

    def refresh_names(self):
        self.presets.blockSignals(True)
        self.presets.clear()
        self.presets.addItems([*BUILTINS, *self.store.custom])
        self.presets.setCurrentText(self.selected)
        self.presets.blockSignals(False)
        for key in ("rename", "delete", "update"):
            self.actions[key].setEnabled(self.selected in self.store.custom)
        self.actions["restore"].setEnabled(self.selected in BUILTINS)

    def select(self, name):
        self.selected = name
        self.refresh_names()
        self.load_style((BUILTINS | self.store.custom)[name])

    def load_style(self, style):
        self.loading = True
        self.style = style
        for key in ("en", "hi"):
            family = style.font if key == "en" else style.hindi_font
            widget = self.fields[key + "_weight"]
            widget.clear()
            for weight in weights(family):
                widget.addItem(WEIGHTS[weight], weight)
            italic = self.fields[key + "_italic"]
            italic.setEnabled(has_italic(family))
            italic.setToolTip("Genuine italic face" if has_italic(family) else "This family has upright faces only.")
        for key, widget in self.fields.items():
            value = getattr(style, key)
            if isinstance(widget, QComboBox):
                widget.setCurrentIndex(widget.findData(value))
            elif isinstance(widget, QCheckBox):
                widget.setChecked(value)
            elif isinstance(widget, QSpinBox):
                widget.setValue(round(value))
            else:
                fill = value or style.normal
                widget.setText(value or "Base color")
                ink = "#141923" if QColor(fill).lightness() > 134 else "#FFFFFF"
                widget.setStyleSheet(f"background-color: {fill}; color: {ink};")
        self.loading = False
        self.refresh_preview()

    def changed(self):
        if self.loading:
            return
        values = {}
        for key, widget in self.fields.items():
            if isinstance(widget, QComboBox):
                values[key] = widget.currentData()
            elif isinstance(widget, QCheckBox):
                values[key] = widget.isChecked()
            elif isinstance(widget, QSpinBox):
                values[key] = widget.value()
        style = replace(self.style, **values)
        if (style.font, style.hindi_font) != (self.style.font, self.style.hindi_font):
            en, hi = style.faces
            self.load_style(replace(style, en_weight=en.weight, hi_weight=hi.weight,
                                    en_italic=en.italic, hi_italic=hi.italic))
        else:
            self.style = style
            self.refresh_preview()

    def refresh_preview(self):
        self.preview.request(self.style, self.sample.currentData())

    def pick(self, key):
        color = QColorDialog.getColor(QColor(getattr(self.style, key) or self.style.normal), self)
        if color.isValid():
            self.set_color(key, color.name())

    def set_color(self, key, value):
        self.load_style(replace(self.style, **{key: value}))

    def manage(self, op):
        name = self.selected
        if op == "restore":
            self.load_style(BUILTINS[name])
            return
        new_name = None
        if op in ("rename", "create"):
            new_name, ok = QInputDialog.getText(self, "Custom preset", "Preset name",
                                                text=name if op == "rename" else "")
            if not ok:
                return
            new_name = new_name.strip()
        if op == "delete" and QMessageBox.question(self, "Delete preset", f"Delete “{name}”?") != QMessageBox.Yes:
            return
        try:
            self.store.change(op, new_name if op == "create" else name, style=self.style, new_name=new_name)
            self.selected = new_name or (self.store.selected if op == "delete" else name)
            self.refresh_names()
            if op == "delete":
                self.select(self.selected)
        except EngineError as exc:
            self.notice.setText(str(exc))

    def apply(self):
        try:
            self.style.validate()
            if not self.store.read_only:
                self.store.change("apply", self.selected, style=self.style)
            self.accept()
        except EngineError as exc:
            self.notice.setText(str(exc))

    def done(self, result):
        self.preview.shutdown()
        super().done(result)

