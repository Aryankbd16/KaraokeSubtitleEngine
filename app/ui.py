from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QFontDatabase
from PySide6.QtWidgets import (
    QBoxLayout, QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from . import __version__
from .alignment import LANGUAGES, Wav2VecAligner, cache_dir, check_language
from .core import AUDIO, VIDEO, Cancellation, Cancelled, EngineError, Project, Style, validate_file
from .jobs import Job, Result
from .media import Media, MediaInfo, duration_warning
from .presets import BUILTINS, PresetStore
from .preview import SubtitlePreview
from .studio import StudioDialog
from .theme import THEME_QSS, apply_theme
from .widgets import (
    ColorSwatchButton, SectionCard, StatusBadge, StudioMark, StyleSummaryStrip,
    ensure_bundled_fonts, make_divider, make_label, set_prop,
)

LOG = logging.getLogger(__name__)
THEME = THEME_QSS


def label(text: str, role: str = "") -> QLabel:
    return make_label(text, role=role)


def combo(*values: str) -> QComboBox:
    widget = QComboBox()
    widget.addItems(values)
    return widget


def spin(low: int, high: int, value: int) -> QSpinBox:
    widget = QSpinBox()
    widget.setRange(low, high)
    widget.setValue(value)
    return widget


def button(text: str, action: Callable, variant: str = "", tooltip: str = "") -> QPushButton:
    widget = QPushButton(text)
    if variant:
        widget.setProperty("variant", variant)
    if tooltip:
        widget.setToolTip(tooltip)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.clicked.connect(action)
    return widget


def row(*widgets: QWidget, spacing: int = 8) -> QWidget:
    wrapper = QWidget()
    layout = QHBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for widget in widgets:
        layout.addWidget(widget)
    return wrapper


class Worker(QObject):
    result = Signal(object)
    problem = Signal(str)
    progress = Signal(int, str)
    done = Signal()

    def __init__(self, action: Callable[[Cancellation, Callable[[int, str], None]], object]) -> None:
        super().__init__()
        self.action = action
        self.cancel = Cancellation()

    @Slot()
    def run(self) -> None:
        try:
            self.result.emit(self.action(self.cancel, self.progress.emit))
        except Cancelled as exc:
            self.problem.emit(str(exc))
        except EngineError as exc:
            LOG.error("Processing error", exc_info=True)
            self.problem.emit(str(exc))
        except Exception:
            LOG.exception("Unexpected processing failure")
            self.problem.emit("Processing failed. Open the diagnostic log from Settings.")
        finally:
            self.done.emit()


class MainWindow(QMainWindow):
    def __init__(self, aligner: Wav2VecAligner, log_path: Path) -> None:
        super().__init__()
        self.aligner, self.log_path = aligner, log_path
        self.job = None
        self.video: Path | None = None
        self.audio: Path | None = None
        self.folder: Path | None = None
        self.video_info: MediaInfo | None = None
        self.audio_info: MediaInfo | None = None
        self.output: Result | None = None
        self.thread: QThread | None = None
        self.worker: Worker | None = None
        self.success: Callable = lambda _: None
        self.close_pending = False
        self.classic_color_buttons: dict[str, ColorSwatchButton] = {}

        self.setWindowTitle("Karaoke Subtitle Engine · Creative Subtitle Studio")
        self.resize(1140, 770)
        self.setMinimumSize(740, 460)
        apply_theme(self)

        root = QWidget()
        self.setCentralWidget(root)
        shell = QVBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        shell.addWidget(self._build_header())

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        shell.addWidget(self.scroll, 1)

        content = QWidget()
        self.scroll.setWidget(content)
        workspace = QVBoxLayout(content)
        workspace.setContentsMargins(20, 16, 20, 18)
        workspace.setSpacing(14)

        self.make_settings(workspace)

        self.columns = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.columns.setContentsMargins(0, 0, 0, 0)
        self.columns.setSpacing(14)
        workspace.addLayout(self.columns, 1)

        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(14)
        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(14)

        self.columns.addLayout(left_col, 7)
        self.columns.addLayout(right_col, 5)

        self.make_media(left_col)
        self.make_script(left_col)
        left_col.addStretch(1)

        self.make_style(right_col)
        self.make_output(right_col)
        right_col.addStretch(1)

        self._input_surfaces = [self.settings, self.media_card, self.script_card, self.studio_card]
        shell.addWidget(self._build_footer())
        self._update_columns_direction()

    def _build_header(self) -> QFrame:
        bar = QFrame(objectName="header_bar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 11, 20, 11)
        layout.setSpacing(12)

        layout.addWidget(StudioMark(34))
        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(1)
        titles.addWidget(make_label("Karaoke Subtitle Engine", role="title", wrap=False))
        titles.addWidget(make_label("Creative Subtitle Studio", role="subtitle", wrap=False))
        layout.addLayout(titles)
        layout.addStretch(1)

        layout.addWidget(StatusBadge(f"v{__version__}", "neutral"))
        self.settings_button = button("Settings", self.toggle_settings, variant="ghost",
                                      tooltip="Configure encoding quality, alignment device, ASS export, and logs")
        self.settings_button.setCheckable(True)
        layout.addWidget(self.settings_button)
        return bar

    def _build_footer(self) -> QFrame:
        bar = QFrame(objectName="footer_bar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(14)

        status_col = QVBoxLayout()
        status_col.setContentsMargins(0, 0, 0, 0)
        status_col.setSpacing(3)
        status_eyebrow = make_label("STATUS", role="eyebrow", wrap=False)
        self.status = make_label("Choose a video and enter its script.", role="muted")
        self.status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        status_col.addWidget(status_eyebrow)
        status_col.addWidget(self.status)
        layout.addLayout(status_col, 1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(210)
        layout.addWidget(self.progress_bar)

        self.cancel_button = button("Cancel", self.cancel, variant="danger",
                                    tooltip="Cancel the active alignment or export task")
        self.cancel_button.setEnabled(False)
        self.generate = button("Generate Karaoke Video", self.start_job,
                               tooltip="Align spoken words and render burned-in karaoke captions")
        self.generate.setObjectName("generate")
        layout.addWidget(self.cancel_button)
        layout.addWidget(self.generate)
        return bar

    def make_settings(self, parent: QVBoxLayout) -> None:
        self.settings = SectionCard(
            "Export & Engine Settings",
            "Quality, hardware acceleration, standalone ASS output, and diagnostics.",
        )
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)

        self.crf = spin(15, 29, 20)
        self.crf.setToolTip("Lower values yield higher visual quality and larger MP4 files (default: 20).")
        self.device = combo("CPU", "Auto · NVIDIA CUDA when available")
        self.device.setToolTip("Device used for acoustic forced alignment. FFmpeg encoding always runs on CPU.")
        self.save_ass = QCheckBox("Save standalone .ass subtitle file alongside the video")

        grid.addWidget(make_label("Encoding quality (CRF)", role="field"), 0, 0)
        grid.addWidget(self.crf, 1, 0)
        grid.addWidget(make_label("Alignment device", role="field"), 0, 1)
        grid.addWidget(self.device, 1, 1)
        grid.addWidget(self.save_ass, 2, 0, 1, 2)

        actions = row(
            button("Open Model Folder", self.open_models, tooltip="Open local acoustic model cache directory"),
            button("Open Diagnostic Log", lambda: self.open_path(self.log_path),
                   tooltip="Open rotating engine.log for troubleshooting"),
        )
        actions.layout().addStretch(1)
        grid.addWidget(actions, 3, 0, 1, 2)

        self.settings.body_layout.addLayout(grid)
        parent.addWidget(self.settings)
        self.settings.hide()

    def toggle_settings(self) -> None:
        show = self.settings.isHidden()
        self.settings.setVisible(show)
        self.settings_button.setChecked(show)
        if show:
            self.scroll.ensureWidgetVisible(self.settings)

    def make_media(self, parent: QVBoxLayout) -> None:
        self.media_card = SectionCard(
            "Media & Audio Sources",
            "Select your source video, optional replacement audio, sync offset, and output destination.",
        )

        # Video slot
        self.video_slot = QFrame(objectName="media_slot")
        self.video_slot.setProperty("populated", False)
        v_layout = QVBoxLayout(self.video_slot)
        v_layout.setContentsMargins(11, 8, 11, 8)
        v_layout.setSpacing(4)
        v_top = QHBoxLayout()
        v_top.setSpacing(8)
        v_top.addWidget(make_label("SOURCE VIDEO", role="eyebrow", wrap=False))
        self.video_badge = StatusBadge("Required", "accent")
        v_top.addWidget(self.video_badge)
        v_top.addStretch(1)
        v_top.addWidget(button("Choose Video…", lambda: self.choose_media(False),
                               tooltip="Select an MP4, MOV, MKV, AVI, or WebM video"))
        v_layout.addLayout(v_top)
        self.video_label = make_label("No video selected", role="muted")
        self.video_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v_layout.addWidget(self.video_label)
        self.media_card.body_layout.addWidget(self.video_slot)

        # Audio & sync slot
        self.audio_slot = QFrame(objectName="media_slot")
        self.audio_slot.setProperty("populated", False)
        a_layout = QVBoxLayout(self.audio_slot)
        a_layout.setContentsMargins(11, 8, 11, 8)
        a_layout.setSpacing(6)
        a_top = QHBoxLayout()
        a_top.setSpacing(8)
        a_top.addWidget(make_label("AUDIO TRACK", role="eyebrow", wrap=False))
        self.audio_badge = StatusBadge("Embedded", "neutral")
        a_top.addWidget(self.audio_badge)
        a_top.addStretch(1)
        a_top.addWidget(button("Choose Audio…", lambda: self.choose_media(True),
                               tooltip="Use a separate WAV, MP3, M4A, AAC, FLAC, or OGG track"))
        self.clear_audio_btn = button("Use Video Audio", self.clear_audio, variant="ghost",
                                      tooltip="Revert to the video's embedded audio track")
        self.clear_audio_btn.setEnabled(False)
        a_top.addWidget(self.clear_audio_btn)
        a_layout.addLayout(a_top)

        self.audio_label = make_label("Use audio from video", role="muted")
        a_layout.addWidget(self.audio_label)

        offset_row = QHBoxLayout()
        offset_row.setSpacing(10)
        offset_row.addWidget(make_label("Replacement audio offset", role="field", wrap=False))
        self.offset = QDoubleSpinBox()
        self.offset.setRange(-120, 120)
        self.offset.setDecimals(3)
        self.offset.setSingleStep(0.05)
        self.offset.setSuffix(" s")
        self.offset.setEnabled(False)
        self.offset.setFixedWidth(120)
        self.offset.valueChanged.connect(self.update_sync)
        offset_row.addWidget(self.offset)
        offset_row.addStretch(1)
        a_layout.addLayout(offset_row)

        self.sync_hint = make_label("", role="hint")
        a_layout.addWidget(self.sync_hint)
        self.media_card.body_layout.addWidget(self.audio_slot)

        # Output folder slot
        folder_slot = QFrame(objectName="media_slot")
        f_layout = QHBoxLayout(folder_slot)
        f_layout.setContentsMargins(12, 9, 12, 9)
        f_layout.setSpacing(10)
        f_text = QVBoxLayout()
        f_text.setSpacing(2)
        f_text.addWidget(make_label("OUTPUT FOLDER", role="eyebrow", wrap=False))
        self.folder_label = make_label("Same folder as the video", role="muted")
        f_text.addWidget(self.folder_label)
        f_layout.addLayout(f_text, 1)
        f_layout.addWidget(button("Choose Folder…", self.choose_folder,
                                  tooltip="Choose where exported MP4 and alignment JSON files are written"))
        self.media_card.body_layout.addWidget(folder_slot)

        parent.addWidget(self.media_card)
        self.update_sync()

    def make_script(self, parent: QVBoxLayout) -> None:
        self.counter = StatusBadge("0 words · 0 characters", "neutral")
        self.script_card = SectionCard(
            "Spoken Script",
            "Enter the exact spoken or sung words in order. Separate caption paragraphs with a blank line.",
            header_widget=self.counter,
        )

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("Paste the exact words in the order they are spoken or sung…")
        self.editor.setMinimumHeight(140)
        self.editor.textChanged.connect(self.update_script)
        self.script_card.body_layout.addWidget(self.editor)

        lang_row = QHBoxLayout()
        lang_row.setSpacing(10)
        lang_row.addWidget(make_label("Alignment language", role="field", wrap=False))
        self.language = QComboBox()
        for code, item in LANGUAGES.items():
            self.language.addItem(item.label, code)
        self.language.setMinimumWidth(190)
        lang_row.addWidget(self.language)
        lang_row.addStretch(1)
        self.script_card.body_layout.addLayout(lang_row)

        display_panel = QFrame(objectName="sub_panel")
        dp_layout = QVBoxLayout(display_panel)
        dp_layout.setContentsMargins(12, 10, 12, 10)
        dp_layout.setSpacing(8)
        self.display_toggle = QCheckBox("Use separate display text")
        self.display_toggle.setToolTip("Keep monolingual alignment while displaying mixed Hindi/English words.")
        dp_layout.addWidget(self.display_toggle)
        self.display_editor = QPlainTextEdit()
        self.display_editor.setPlaceholderText(
            "One display word per spoken word. Hindi and English can be mixed (e.g. हर word चमके)."
        )
        self.display_editor.setMaximumHeight(82)
        self.display_toggle.toggled.connect(self.display_editor.setVisible)
        dp_layout.addWidget(self.display_editor)
        self.display_editor.hide()
        self.script_card.body_layout.addWidget(display_panel)

        parent.addWidget(self.script_card)

    def make_style(self, parent: QVBoxLayout) -> None:
        self.store = PresetStore(cache_dir() / "subtitle-presets.json")
        self.studio_style = self.store.current
        self.preset_name = self.store.selected
        self.style_label = StatusBadge(self.preset_name, "accent")

        self.studio_card = SectionCard(
            "Creative Subtitle Studio",
            "Customize presets, bilingual fonts, karaoke colours, outlines, and placement.",
            header_widget=self.style_label,
        )

        self.style_summary = StyleSummaryStrip()
        self.style_summary.update_style(self.preset_name, self.studio_style)
        self.studio_card.body_layout.addWidget(self.style_summary)

        self.studio_button = button("Open Creative Subtitle Studio", self.open_studio,
                                    tooltip="Launch live frame-rendered subtitle styling workspace")
        self.studio_button.setMinimumHeight(36)
        self.studio_card.body_layout.addWidget(self.studio_button)

        if self.store.notice:
            notice_box = QFrame(objectName="notice_bar")
            nb_layout = QHBoxLayout(notice_box)
            nb_layout.setContentsMargins(10, 8, 10, 8)
            nb_layout.addWidget(make_label(self.store.notice, tone="warning"))
            self.studio_card.body_layout.addWidget(notice_box)

        self.studio_card.body_layout.addWidget(make_divider())

        self.classic = QCheckBox("Use classic V1 styling")
        self.classic.setToolTip("Switch to original V1 single-font ASS controls and system fonts.")
        self.studio_card.body_layout.addWidget(self.classic)

        classic_panel = QFrame(objectName="sub_panel")
        self.studio_card.body_layout.addWidget(classic_panel)
        form = QFormLayout(classic_panel)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(8)
        self.classic.toggled.connect(classic_panel.setVisible)
        self.classic.toggled.connect(self.studio_button.setDisabled)
        classic_panel.hide()

        self.colors = Style()
        ensure_bundled_fonts()
        fonts = QFontDatabase.families()
        self.font = combo(*(fonts or ["Sans Serif"]))
        if "Segoe UI" in fonts:
            self.font.setCurrentText("Segoe UI")
        elif "DejaVu Sans" in fonts:
            self.font.setCurrentText("DejaVu Sans")
        self.default_font = self.font.currentText()
        self.size, self.words, self.margin = spin(16, 120, 48), spin(1, 20, 7), spin(0, 200, 64)
        self.stroke, self.shadow = spin(0, 10, 3), spin(0, 10, 1)
        self.horizontal = combo("Left", "Center", "Right")
        self.horizontal.setCurrentIndex(1)
        self.vertical = combo("Bottom", "Middle", "Top")

        form.addRow("Font", self.font)
        form.addRow("Size / Words / Margin", row(self.size, self.words, self.margin, spacing=6))
        form.addRow("Outline / Shadow", row(self.stroke, self.shadow, spacing=6))
        form.addRow("Placement", row(self.horizontal, self.vertical, spacing=6))

        color_grid = QGridLayout()
        color_grid.setSpacing(6)
        for index, (title, key) in enumerate((
            ("Upcoming", "normal"),
            ("Active", "active"),
            ("Completed", "completed"),
            ("Outline", "outline"),
        )):
            hex_val = getattr(self.colors, key)
            btn = ColorSwatchButton(hex_val, f"{title}")
            btn.clicked.connect(lambda checked=False, k=key: self.choose_color(k))
            self.classic_color_buttons[key] = btn
            color_grid.addWidget(btn, index // 2, index % 2)
        color_wrap = QWidget()
        color_wrap.setLayout(color_grid)
        form.addRow("Colors", color_wrap)

        self.preview = SubtitlePreview()
        form.addRow(self.preview)

        for control in (self.font, self.horizontal, self.vertical):
            control.currentIndexChanged.connect(self.update_preview)
        self.language.currentIndexChanged.connect(self.update_language)
        for control in (self.size, self.margin, self.stroke, self.shadow):
            control.valueChanged.connect(self.update_preview)
        self.update_preview()

        parent.addWidget(self.studio_card)

    def make_output(self, parent: QVBoxLayout) -> None:
        self.output_badge = StatusBadge("Awaiting Export", "neutral")
        self.output_card = SectionCard(
            "Verified Output",
            "Exported MP4, alignment JSON report, and quick playback actions.",
            header_widget=self.output_badge,
        )

        output_box = QFrame(objectName="sub_panel")
        ob_layout = QVBoxLayout(output_box)
        ob_layout.setContentsMargins(12, 10, 12, 10)
        ob_layout.setSpacing(4)
        self.output_label = make_label("A verified export will appear here.", role="muted")
        self.output_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        ob_layout.addWidget(self.output_label)
        self.output_card.body_layout.addWidget(output_box)

        self.output_controls = QWidget()
        oc_grid = QGridLayout(self.output_controls)
        oc_grid.setContentsMargins(0, 0, 0, 0)
        oc_grid.setSpacing(8)
        oc_grid.addWidget(button("Play Video", lambda: self.open_output("video")), 0, 0)
        oc_grid.addWidget(button("Open Folder", lambda: self.open_output("folder")), 0, 1)
        oc_grid.addWidget(button("Alignment Report", lambda: self.open_output("report")), 1, 0)
        oc_grid.addWidget(button("Generate Another", self.reset, variant="ghost"), 1, 1)
        self.output_controls.setEnabled(False)
        self.output_card.body_layout.addWidget(self.output_controls)

        parent.addWidget(self.output_card)

    def _set_inputs_enabled(self, enabled: bool) -> None:
        for surface in self._input_surfaces:
            surface.setEnabled(enabled)

    def _set_status(self, message: str, tone: str = "muted") -> None:
        self.status.setText(message)
        set_prop(self.status, "tone", tone)

    def _update_columns_direction(self) -> None:
        direction = (
            QBoxLayout.Direction.LeftToRight
            if self.width() >= 880
            else QBoxLayout.Direction.TopToBottom
        )
        if self.columns.direction() != direction:
            self.columns.setDirection(direction)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_columns_direction()

    def open_studio(self) -> None:
        text = self.display_editor.toPlainText() if self.display_toggle.isChecked() else self.editor.toPlainText()
        dialog = StudioDialog(self.store, self.preset_name, self.studio_style, self.video,
                              self.video_info, text, self)
        if dialog.exec():
            self.preset_name, self.studio_style = dialog.selected, dialog.style
            self.style_label.setText(self.preset_name)
            self.style_summary.update_style(self.preset_name, self.studio_style)
        elif self.preset_name not in self.store.custom and self.preset_name not in BUILTINS:
            self.preset_name, self.studio_style = self.store.selected, self.store.current
            self.style_label.setText(self.preset_name)
            self.style_summary.update_style(self.preset_name, self.studio_style)
        dialog.deleteLater()

    @Slot()
    def update_language(self) -> None:
        hindi_font = "Noto Sans Devanagari"
        if self.font.currentText() in {self.default_font, hindi_font}:
            self.font.setCurrentText(hindi_font if self.language.currentData() == "hi" else self.default_font)
        self.update_preview()

    def choose_color(self, key: str) -> None:
        color = QColorDialog.getColor(QColor(getattr(self.colors, key)), self)
        if color.isValid():
            self.colors = replace(self.colors, **{key: color.name()})
            btn = self.classic_color_buttons.get(key)
            if btn is not None:
                titles = {"normal": "Upcoming", "active": "Active",
                          "completed": "Completed", "outline": "Outline"}
                btn.set_swatch(color.name(), titles[key])
            self.update_preview()

    def subtitle_style(self) -> Style:
        return replace(self.colors, font=self.font.currentText(), size=self.size.value(),
                       words_per_line=self.words.value(), margin=self.margin.value(),
                       stroke=self.stroke.value(), shadow=self.shadow.value(),
                       horizontal=self.horizontal.currentIndex() + 1,
                       vertical=self.vertical.currentIndex() * 3)

    @Slot()
    def update_preview(self) -> None:
        words = ("हर", "शब्द", "चमके") if self.language.currentData() == "hi" else ("Every", "word", "shines")
        self.preview.show_style(self.subtitle_style(), words)

    @Slot()
    def update_script(self) -> None:
        script = self.editor.toPlainText()
        word_count = len(script.split())
        self.counter.setText(f"{word_count} words · {len(script)} characters")
        self.counter.set_tone("accent" if word_count else "neutral")

    @Slot()
    def update_sync(self) -> None:
        hint = "Positive values delay replacement audio. Negative values advance it."
        tone = "hint"
        if self.video_info and self.audio_info:
            video, audio = self.video_info.video_duration, self.audio_info.audio_duration
            if video and audio:
                warning = duration_warning(video, audio, self.offset.value())
                if warning:
                    hint += "\n" + warning
                    tone = "warning"
        self.sync_hint.setText(hint)
        set_prop(self.sync_hint, "tone", tone)

    def choose_media(self, audio: bool) -> None:
        extensions = AUDIO if audio else VIDEO
        pattern = " ".join("*" + extension for extension in sorted(extensions))
        name, _ = QFileDialog.getOpenFileName(self, "Choose audio" if audio else "Choose video",
                                             "", f"Media ({pattern})")
        if not name:
            return
        path = Path(name)

        def inspect(cancel: Cancellation, _: Callable) -> MediaInfo:
            validate_file(path, extensions)
            info = Media().probe(path, cancel)
            duration = info.audio_duration if audio else info.video_duration
            if duration is None or duration <= 0:
                raise EngineError("This file has no usable audio stream." if audio else
                                  "This file has no usable video stream.")
            return info

        def accepted(info: MediaInfo) -> None:
            audio_desc = (f"{info.audio_codec} · {info.sample_rate} Hz · {info.channels} ch"
                          if info.audio_duration else "No audio stream")
            if audio:
                self.audio, self.audio_info = path, info
                self.audio_label.setText(f"{path.name} · {info.audio_duration:.2f} s · {audio_desc}")
                self.audio_badge.setText("Replacement")
                self.audio_badge.set_tone("accent")
                set_prop(self.audio_slot, "populated", True)
                self.clear_audio_btn.setEnabled(True)
                self.offset.setEnabled(True)
            else:
                self.video, self.video_info = path, info
                self.video_label.setText(f"{path.name} · {info.video_duration:.2f} s · "
                                         f"{info.width} × {info.height} · {info.fps:.2f} fps · "
                                         f"{info.video_codec} · {audio_desc}")
                self.video_badge.setText("Ready")
                self.video_badge.set_tone("success")
                set_prop(self.video_slot, "populated", True)
            self.update_sync()
            self._set_status("Media ready.", "success")

        self.start_task(inspect, accepted, "Inspecting media…", False)

    def clear_audio(self) -> None:
        self.audio = self.audio_info = None
        self.offset.setValue(0)
        self.offset.setEnabled(False)
        self.clear_audio_btn.setEnabled(False)
        self.audio_label.setText("Use audio from video")
        self.audio_badge.setText("Embedded")
        self.audio_badge.set_tone("neutral")
        set_prop(self.audio_slot, "populated", False)
        self.update_sync()

    def choose_folder(self) -> None:
        name = QFileDialog.getExistingDirectory(self, "Choose output folder")
        if name:
            self.folder = Path(name)
            self.folder_label.setText(name)

    def start_job(self) -> None:
        if self.video is None:
            self.error("Choose a video before generating karaoke subtitles.")
            return
        project = Project(self.video, self.audio, self.editor.toPlainText(),
                          self.language.currentData(), self.folder or self.video.parent,
                          self.subtitle_style() if self.classic.isChecked() else self.studio_style,
                          self.offset.value(), self.crf.value(), self.save_ass.isChecked(),
                          "cpu" if self.device.currentIndex() == 0 else "auto",
                          self.display_editor.toPlainText() if self.display_toggle.isChecked() else "")
        try:
            check_language(project.language, project.validate())
            Media()
            if not self.audio and self.video_info and not self.video_info.audio_duration:
                raise EngineError("This video has no audio stream. Choose replacement audio.")
        except EngineError as exc:
            self.error(str(exc))
            return
        needs_model = not self.aligner.ready(project.language)
        if needs_model:
            choice = QMessageBox.question(
                self, "Download alignment model?",
                f"Allow a download of {LANGUAGES[project.language].model} for local processing?\n\n"
                f"Model folder: {self.aligner.cache}\n"
                f"Download size: {'378 MB' if project.language == 'en' else '1.26 GB'}.",
            )
            if choice != QMessageBox.StandardButton.Yes:
                return

        def process(cancel: Cancellation, update: Callable[[int, str], None]) -> Result:
            if needs_model:
                self.aligner.prepare(project.language, cancel, lambda text: update(-1, text))
            if self.job is None:
                self.job = Job(self.aligner)
            return self.job.run(project, cancel, update)

        self.start_task(process, self.show_output, "Starting export…", True)

    def start_task(self, action: Callable, success: Callable, status: str, cancellable: bool) -> None:
        if self.thread is not None:
            return
        self.success = success
        self.thread = QThread(self)
        self.worker = Worker(action)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.show_progress)
        self.worker.result.connect(self.deliver_result)
        self.worker.problem.connect(self.error)
        self.worker.done.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.finish_task)
        self._set_status(status, "muted")
        self.progress_bar.setRange(0, 0)
        self._set_inputs_enabled(False)
        self.generate.setEnabled(False)
        self.cancel_button.setEnabled(cancellable)
        self.thread.start()

    @Slot(object)
    def deliver_result(self, result: object) -> None:
        self.success(result)

    @Slot()
    def finish_task(self) -> None:
        if self.thread:
            self.thread.deleteLater()
        self.thread = self.worker = None
        if self.close_pending:
            self.close()
            return
        self._set_inputs_enabled(True)
        self.generate.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)

    @Slot(int, str)
    def show_progress(self, percent: int, text: str) -> None:
        self._set_status(text, "muted")
        self.progress_bar.setRange(0, 0 if percent < 0 else 100)
        if percent >= 0:
            self.progress_bar.setValue(percent)

    @Slot()
    def cancel(self) -> None:
        if self.worker:
            self.worker.cancel.event.set()
            self.cancel_button.setEnabled(False)
            self._set_status("Cancelling after the current processing step…", "warning")

    @Slot(str)
    def error(self, message: str) -> None:
        self._set_status(message, "error")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

    def show_output(self, result: Result) -> None:
        self.output = result
        detail = "\n".join(result.issues[:8])
        if len(result.issues) > 8:
            detail += f"\n{len(result.issues) - 8} more entries in the alignment report."
        self.output_label.setText(str(result.video) + ("\n\n" + detail if detail else ""))
        self.output_controls.setEnabled(True)
        if result.issues:
            self.output_badge.setText("Review Report")
            self.output_badge.set_tone("warning")
            self._set_status("Video exported. Review the alignment report.", "warning")
        else:
            self.output_badge.setText("Verified")
            self.output_badge.set_tone("success")
            self._set_status("Video exported.", "success")
        self.scroll.ensureWidgetVisible(self.output_card)

    def open_models(self) -> None:
        try:
            self.aligner.cache.mkdir(parents=True, exist_ok=True)
            self.open_path(self.aligner.cache)
        except OSError:
            self.error("Could not create the model folder.")

    def open_path(self, path: Path) -> None:
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve()))):
            self.error(f"Could not open {path.name} with the system default app.")

    def open_output(self, kind: str) -> None:
        if self.output:
            self.open_path({"video": self.output.video, "folder": self.output.video.parent,
                            "report": self.output.report}[kind])

    def reset(self) -> None:
        if self.thread:
            return
        self.video = self.video_info = self.folder = self.output = None
        self.video_label.setText("No video selected")
        self.video_badge.setText("Required")
        self.video_badge.set_tone("accent")
        set_prop(self.video_slot, "populated", False)
        self.folder_label.setText("Same folder as the video")
        self.clear_audio()
        self.editor.clear()
        self.display_editor.clear()
        self.display_toggle.setChecked(False)
        self.output_controls.setEnabled(False)
        self.output_badge.setText("Awaiting Export")
        self.output_badge.set_tone("neutral")
        self.output_label.setText("A verified export will appear here.")
        self.progress_bar.setValue(0)
        self._set_status("Choose a video and enter its script.", "muted")
        self.editor.setFocus()

    def closeEvent(self, event) -> None:
        if self.thread:
            self.close_pending = True
            self.cancel()
            event.ignore()
        else:
            event.accept()
