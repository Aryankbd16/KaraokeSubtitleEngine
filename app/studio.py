"""Creative Subtitle Studio dialog. All controls edit an immutable presentation snapshot."""
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QFormLayout, QFrame, QHBoxLayout,
    QInputDialog, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from .core import EngineError
from .font_library import ENGLISH, HINDI, WEIGHTS, has_italic, weights
from .presets import BUILTINS
from .preview import FramePreview
from .theme import apply_theme
from .widgets import (
    CollapsibleSection, ColorSwatchButton, FontComboBox, PresetCard, StatusBadge,
    ensure_bundled_fonts, make_divider, make_label,
)

SAMPLES = {
    "Mixed": "ज़िंदगी finds उम्मीद in every मुस्कान",
    "Hindi": "ज़िंदगी उम्मीद और विश्वास से हमेशा मुस्कुराती है।",
    "English": "Every word shines a little brighter",
}

PRESET_DESCRIPTIONS = {
    "Clean Reel": "Static bold white · High contrast outline & shadow",
    "Mixed Typography": "Cream Mukta Hindi · Blue italic Noto English",
    "Karaoke Highlight": "White upcoming · Gold active · Muted completed",
    "Poetry / Shayari": "Warm Tiro Devanagari · Italic English · Wide spacing",
}


class StudioDialog(QDialog):
    def __init__(self, store, selected, style, video, info, script, parent=None):
        super().__init__(parent)
        self.store, self.selected, self.style = store, selected, style
        self.loading = True
        self.fields = {}
        self.actions = {}
        self.preset_cards: dict[str, PresetCard] = {}
        self.italic_badges: dict[str, StatusBadge] = {}
        self.color_resets: dict[str, QPushButton] = {}

        ensure_bundled_fonts()
        apply_theme(self)
        self.setWindowTitle("Creative Subtitle Studio")
        self.resize(1160, 720)
        self.setMinimumSize(760, 460)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)

        body.addWidget(self._build_preset_sidebar())
        body.addWidget(self._build_center_stage(video, info, script), 1)
        body.addWidget(self._build_inspector())

        outer.addWidget(self._build_footer())

        self.refresh_names()
        self.presets.currentTextChanged.connect(self.select)
        self.sample.currentIndexChanged.connect(self.refresh_preview)
        self.load_style(style)

    def _build_header(self) -> QFrame:
        bar = QFrame(objectName="header_bar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 10, 18, 10)
        layout.setSpacing(10)

        layout.addWidget(make_label("Creative Subtitle Studio", role="section", wrap=False))
        self.active_preset_badge = StatusBadge(self.selected, "accent")
        layout.addWidget(self.active_preset_badge)
        layout.addStretch(1)

        # Hidden synchronized combobox preserves external/test preset selection contract
        self.presets = QComboBox()
        self.presets.hide()
        layout.addWidget(self.presets)

        specs = (
            ("Save", "update", "", "Save changes to the selected custom preset"),
            ("Save As…", "create", "", "Save the current styling as a new custom preset"),
            ("Rename…", "rename", "", "Rename the selected custom preset"),
            ("Delete…", "delete", "danger", "Delete the selected custom preset"),
            ("Restore Default", "restore", "ghost", "Reload the built-in preset's original values"),
        )
        for title, action, variant, tooltip in specs:
            btn = QPushButton(title)
            if variant:
                btn.setProperty("variant", variant)
            btn.setToolTip(tooltip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.actions[action] = btn
            btn.clicked.connect(lambda checked=False, op=action: self.manage(op))
            layout.addWidget(btn)
        return bar

    def _build_preset_sidebar(self) -> QFrame:
        panel = QFrame(objectName="sidebar_panel")
        panel.setMinimumWidth(215)
        panel.setMaximumWidth(258)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll, 1)

        inner = QWidget()
        scroll.setWidget(inner)
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        layout.addWidget(make_label("BUILT-IN PRESETS", role="eyebrow", wrap=False))
        self.builtin_cards_layout = QVBoxLayout()
        self.builtin_cards_layout.setSpacing(7)
        for name, preset_style in BUILTINS.items():
            card = PresetCard(
                name,
                PRESET_DESCRIPTIONS.get(name, "Built-in studio look"),
                preset_style,
                is_builtin=True,
            )
            card.clicked.connect(self._select_from_card)
            self.preset_cards[name] = card
            self.builtin_cards_layout.addWidget(card)
        layout.addLayout(self.builtin_cards_layout)

        layout.addSpacing(6)
        layout.addWidget(make_label("CUSTOM PRESETS", role="eyebrow", wrap=False))
        self.custom_cards_layout = QVBoxLayout()
        self.custom_cards_layout.setSpacing(7)
        layout.addLayout(self.custom_cards_layout)

        self.custom_empty_label = make_label(
            "No custom presets yet.\nClick Save As… to create one.",
            role="hint",
        )
        layout.addWidget(self.custom_empty_label)
        layout.addStretch(1)
        return panel

    def _build_center_stage(self, video, info, script: str) -> QWidget:
        center = QWidget()
        layout = QVBoxLayout(center)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(make_label("Preview Sample", role="field", wrap=False))
        self.sample = QComboBox()
        if script.strip():
            self.sample.addItem("Current script", " ".join(script.split()[:24]))
        for name, sample in SAMPLES.items():
            self.sample.addItem(name, sample)
        self.sample.setMinimumWidth(140)
        top.addWidget(self.sample)
        top.addStretch(1)
        layout.addLayout(top)

        self.stage_meta = make_label("", role="hint")
        layout.addWidget(self.stage_meta)

        stage = QFrame(objectName="stage_frame")
        stage_layout = QVBoxLayout(stage)
        stage_layout.setContentsMargins(8, 8, 8, 8)
        self.preview = FramePreview(video, info)
        stage_layout.addWidget(self.preview, 1)
        layout.addWidget(stage, 1)

        self.notice_bar = QFrame(objectName="notice_bar")
        nb_layout = QHBoxLayout(self.notice_bar)
        nb_layout.setContentsMargins(10, 7, 10, 7)
        self.notice = make_label("", tone="warning")
        nb_layout.addWidget(self.notice)
        layout.addWidget(self.notice_bar)
        self._set_notice(self.store.notice)
        return center

    def _build_inspector(self) -> QFrame:
        panel = QFrame(objectName="inspector_panel")
        panel.setMinimumWidth(354)
        panel.setMaximumWidth(410)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll, 1)

        inner = QWidget()
        scroll.setWidget(inner)
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(9)

        layout.addWidget(make_label("STYLING INSPECTOR", role="eyebrow", wrap=False))

        # 1. Typography
        typo = CollapsibleSection("Typography", expanded=True)
        for key, badge_text, title, families in (
            ("en", "EN", "English Typography", ENGLISH),
            ("hi", "HI", "Hindi Typography", HINDI),
        ):
            sub = QFrame(objectName="sub_panel")
            sub_layout = QVBoxLayout(sub)
            sub_layout.setContentsMargins(10, 9, 10, 9)
            sub_layout.setSpacing(7)

            hdr = QHBoxLayout()
            hdr.setSpacing(6)
            hdr.addWidget(StatusBadge(badge_text, "accent" if key == "hi" else "neutral"))
            hdr.addWidget(make_label(title, role="field", wrap=False), 1)
            italic_badge = StatusBadge("Upright only", "neutral")
            self.italic_badges[key] = italic_badge
            hdr.addWidget(italic_badge)
            sub_layout.addLayout(hdr)

            sub_form = QFormLayout()
            sub_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
            sub_form.setContentsMargins(0, 0, 0, 0)
            sub_form.setSpacing(6)

            family = FontComboBox()
            for name in families:
                family.add_family(name)
            self.field(sub_form, "font" if key == "en" else "hindi_font", "Family", family)

            weight = QComboBox()
            weight.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            weight.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            weight.setMinimumContentsLength(6)
            self.fields[key + "_weight"] = weight
            weight.currentIndexChanged.connect(self.changed)
            sub_form.addRow("Weight", weight)

            italic = QCheckBox("Use italic face")
            self.fields[key + "_italic"] = italic
            italic.toggled.connect(self.changed)
            sub_form.addRow("Style", italic)

            sub_layout.addLayout(sub_form)
            typo.content_layout.addWidget(sub)

        size_form = QFormLayout()
        size_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        size_form.setContentsMargins(2, 2, 2, 0)
        size_form.setSpacing(6)
        self.number(size_form, "size", "Shared font size", 16, 120, suffix=" px")
        typo.content_layout.addLayout(size_form)
        layout.addWidget(typo)

        # 2. Colours
        colors = CollapsibleSection("Colours", expanded=True)
        self.check(colors.content_layout, "karaoke", "Highlight active word")
        self.check(colors.content_layout, "color_completed", "Recolor completed words")
        colors.content_layout.addWidget(make_divider())

        color_form = QFormLayout()
        color_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        color_form.setContentsMargins(0, 0, 0, 0)
        color_form.setSpacing(7)
        for key, title in (
            ("normal", "Base text"),
            ("en_color", "English text"),
            ("hi_color", "Hindi text"),
            ("active", "Active word"),
            ("completed", "Completed words"),
        ):
            self._add_color_row(color_form, key, title, allow_reset=key in ("en_color", "hi_color"))
        colors.content_layout.addLayout(color_form)
        layout.addWidget(colors)

        # 3. Outline & Shadow
        effects = CollapsibleSection("Outline & Shadow", expanded=False)
        self.check(effects.content_layout, "outline_enabled", "Enable outline")
        outline_form = QFormLayout()
        outline_form.setContentsMargins(0, 0, 0, 0)
        outline_form.setSpacing(7)
        self._add_color_row(outline_form, "outline", "Outline colour", allow_reset=False)
        self.number(outline_form, "stroke", "Thickness", 0, 10, suffix=" px")
        effects.content_layout.addLayout(outline_form)

        effects.content_layout.addWidget(make_divider())

        self.check(effects.content_layout, "shadow_enabled", "Enable drop shadow")
        shadow_form = QFormLayout()
        shadow_form.setContentsMargins(0, 0, 0, 0)
        shadow_form.setSpacing(7)
        self._add_color_row(shadow_form, "shadow_color", "Shadow colour", allow_reset=False)
        self.number(shadow_form, "shadow", "Distance", 0, 10, suffix=" px")
        self.number(shadow_form, "shadow_opacity", "Opacity", 0, 100, suffix=" %")
        effects.content_layout.addLayout(shadow_form)
        layout.addWidget(effects)

        # 4. Background
        bg = CollapsibleSection("Background", expanded=False)
        self.check(bg.content_layout, "background", "Translucent background box")
        bg_form = QFormLayout()
        bg_form.setContentsMargins(0, 0, 0, 0)
        bg_form.setSpacing(7)
        self._add_color_row(bg_form, "box_color", "Box colour", allow_reset=False)
        self.number(bg_form, "box_opacity", "Box opacity", 0, 100, suffix=" %")
        bg.content_layout.addLayout(bg_form)
        layout.addWidget(bg)

        # 5. Position & Layout
        pos = CollapsibleSection("Position & Layout", expanded=False)
        pos_form = QFormLayout()
        pos_form.setContentsMargins(0, 0, 0, 0)
        pos_form.setSpacing(7)
        for key, title, options in (
            ("horizontal", "Horizontal align", (("Left", 1), ("Center", 2), ("Right", 3))),
            ("vertical", "Vertical position", (("Bottom", 0), ("Middle", 3), ("Top", 6))),
        ):
            combo = QComboBox()
            for name, value in options:
                combo.addItem(name, value)
            self.field(pos_form, key, title, combo)
        self.number(pos_form, "margin", "Edge margin", 0, 200, suffix=" px")
        self.number(pos_form, "line_gap", "Line spacing", 0, 100, suffix=" px")
        self.number(pos_form, "words_per_line", "Words per line", 1, 20)
        self.number(pos_form, "width_percent", "Maximum width", 20, 100, suffix=" %")
        pos.content_layout.addLayout(pos_form)
        layout.addWidget(pos)

        layout.addStretch(1)
        return panel

    def _build_footer(self) -> QFrame:
        bar = QFrame(objectName="footer_bar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 10, 18, 10)
        layout.setSpacing(10)

        layout.addWidget(
            make_label("Live preview renders with FFmpeg/libass. Click Apply Look to use it for export.", role="hint"),
            1,
        )
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        apply_btn = QPushButton("Apply Look")
        apply_btn.setProperty("variant", "primary")
        apply_btn.setDefault(True)
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.clicked.connect(self.apply)
        self._apply_btn = apply_btn
        layout.addWidget(cancel_btn)
        layout.addWidget(apply_btn)
        return bar

    def _add_color_row(self, form: QFormLayout, key: str, title: str, allow_reset: bool) -> None:
        btn = ColorSwatchButton()
        self.fields[key] = btn
        btn.clicked.connect(lambda checked=False, field=key: self.pick(field))
        if allow_reset:
            group = QHBoxLayout()
            group.setSpacing(6)
            group.addWidget(btn, 1)
            reset = QPushButton("Reset")
            reset.setProperty("variant", "ghost")
            reset.setCursor(Qt.CursorShape.PointingHandCursor)
            reset.setToolTip("Inherit the Base text colour")
            reset.clicked.connect(lambda checked=False, field=key: self.set_color(field, None))
            self.color_resets[key] = reset
            group.addWidget(reset)
            form.addRow(title, group)
        else:
            form.addRow(title, btn)

    def _set_notice(self, text: str) -> None:
        self.notice.setText(text)
        self.notice_bar.setVisible(bool(text.strip()))

    def _select_from_card(self, name: str) -> None:
        if name != self.selected:
            self.presets.setCurrentText(name)

    def field(self, form, key, title, widget):
        self.fields[key] = widget
        form.addRow(title, widget)
        if isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(self.changed)
        elif isinstance(widget, QCheckBox):
            widget.toggled.connect(self.changed)
        else:
            widget.valueChanged.connect(self.changed)

    def check(self, container, key, title):
        widget = QCheckBox(title)
        self.fields[key] = widget
        if isinstance(container, QFormLayout):
            container.addRow(widget)
        else:
            container.addWidget(widget)
        widget.toggled.connect(self.changed)

    def number(self, form, key, title, low, high, suffix: str = ""):
        widget = QSpinBox()
        widget.setRange(low, high)
        if suffix:
            widget.setSuffix(suffix)
        self.field(form, key, title, widget)

    def refresh_names(self):
        self.presets.blockSignals(True)
        self.presets.clear()
        self.presets.addItems([*BUILTINS, *self.store.custom])
        self.presets.setCurrentText(self.selected)
        self.presets.blockSignals(False)

        # Rebuild custom preset cards
        while self.custom_cards_layout.count():
            item = self.custom_cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                self.preset_cards.pop(getattr(widget, "preset_name", ""), None)
                widget.deleteLater()

        for name, custom_style in self.store.custom.items():
            card = PresetCard(
                name,
                f"{custom_style.hindi_font} · {custom_style.font}",
                custom_style,
                is_builtin=False,
            )
            card.clicked.connect(self._select_from_card)
            self.preset_cards[name] = card
            self.custom_cards_layout.addWidget(card)

        self.custom_empty_label.setVisible(not self.store.custom)

        for name, card in self.preset_cards.items():
            card.set_selected(name == self.selected)

        is_custom = self.selected in self.store.custom
        self.active_preset_badge.setText(
            f"{self.selected} · {'Custom' if is_custom else 'Built-in'}"
        )
        self.active_preset_badge.set_tone("accent" if is_custom else "neutral")

        for key in ("rename", "delete", "update"):
            self.actions[key].setEnabled(is_custom)
        self.actions["restore"].setEnabled(self.selected in BUILTINS)

    def select(self, name):
        if name not in BUILTINS and name not in self.store.custom:
            return
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
            supported = has_italic(family)
            italic.setEnabled(supported)
            italic.setToolTip("Genuine italic face" if supported else "This family has upright faces only.")
            badge = self.italic_badges[key]
            badge.setText("Italic ready" if supported else "Upright only")
            badge.set_tone("success" if supported else "neutral")
        for key, widget in self.fields.items():
            value = getattr(style, key)
            if isinstance(widget, QComboBox):
                widget.setCurrentIndex(widget.findData(value))
            elif isinstance(widget, QCheckBox):
                widget.setChecked(value)
            elif isinstance(widget, QSpinBox):
                widget.setValue(round(value))
            elif isinstance(widget, ColorSwatchButton):
                fill = value or style.normal
                label_text = value.upper() if value else "Base"
                widget.set_swatch(fill, label_text)
                if key in self.color_resets:
                    self.color_resets[key].setEnabled(value is not None)
            else:
                fill = value or style.normal
                widget.setText(value or "Base color")
                ink = "#141923" if QColor(fill).lightness() > 134 else "#FFFFFF"
                widget.setStyleSheet(f"background-color: {fill}; color: {ink};")

        mode = "Karaoke" if style.karaoke else "Static"
        self.stage_meta.setText(
            f"EN: {style.font} {WEIGHTS[style.en_weight]} · "
            f"HI: {style.hindi_font} {WEIGHTS[style.hi_weight]} · {mode}"
        )
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
            mode = "Karaoke" if style.karaoke else "Static"
            self.stage_meta.setText(
                f"EN: {style.font} {WEIGHTS[style.en_weight]} · "
                f"HI: {style.hindi_font} {WEIGHTS[style.hi_weight]} · {mode}"
            )
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
            new_name, ok = QInputDialog.getText(
                self,
                "Rename Custom Preset" if op == "rename" else "Save Custom Preset",
                "Preset name (1–64 characters):",
                text=name if op == "rename" else "",
            )
            if not ok:
                return
            new_name = new_name.strip()
        if op == "delete" and QMessageBox.question(
            self, "Delete Preset", f"Delete custom preset “{name}”?"
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.change(op, new_name if op == "create" else name, style=self.style, new_name=new_name)
            self.selected = new_name or (self.store.selected if op == "delete" else name)
            self._set_notice("")
            self.refresh_names()
            if op == "delete":
                self.select(self.selected)
        except EngineError as exc:
            self._set_notice(str(exc))

    def apply(self):
        try:
            self.style.validate()
            if not self.store.read_only:
                self.store.change("apply", self.selected, style=self.style)
            self.accept()
        except EngineError as exc:
            self._set_notice(str(exc))

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_btn.setFocus()

    def done(self, result):
        self.preview.shutdown()
        super().done(result)
