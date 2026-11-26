from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from . import __version__
from .alignment import LANGUAGES, Wav2VecAligner, check_language
from .core import AUDIO, VIDEO, Cancellation, Cancelled, EngineError, Project, Style, validate_file
from .jobs import Job, Result
from .media import FONT_DIR, Media, MediaInfo, duration_warning
from .preview import SubtitlePreview

LOG = logging.getLogger(__name__)
THEME = """
QWidget { color: #e5ebf6; background: #10141d; font-size: 13px; }
QLabel { background: transparent; }
QLabel#title { font-size: 26px; font-weight: 700; }
QLabel#heading { font-size: 16px; font-weight: 700; }
QLabel#mark { color: #ffd65a; font-size: 26px; }
QFrame#card { background: #191f2d; border: 1px solid #2c374b; border-radius: 12px; }
QFrame#card QWidget { background: transparent; }
QFrame#card QPlainTextEdit, QFrame#card QComboBox, QFrame#card QSpinBox,
QFrame#card QDoubleSpinBox, QPushButton {
    background: #131a27; border: 1px solid #35435a; border-radius: 6px; padding: 7px;
}
QFrame#card QPushButton { background: #222d41; }
QPushButton:hover, QFrame#card QPushButton:hover { border-color: #aebcdd; }
QPushButton:disabled { color: #8792a5; }
QPushButton#generate { background: #ffd65a; color: #1a170b; font-weight: 700; padding: 11px; }
QPushButton#generate:disabled { background: #71643e; }
QFrame#card QLabel#preview { background: #10141d; border: 1px solid #35435a; border-radius: 8px; }
QComboBox QAbstractItemView { background: #191f2d; selection-background-color: #3b4763; }
QProgressBar { border: 1px solid #35435a; border-radius: 4px; text-align: center; }
QProgressBar::chunk { background: #ad8541; border-radius: 3px; }
QScrollArea { border: none; }
"""


def label(text: str, role: str = "") -> QLabel:
    widget = QLabel(text, objectName=role)
    widget.setWordWrap(True)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    return widget


def combo(*values: str) -> QComboBox:
    widget = QComboBox()
    widget.addItems(values)
    return widget


def spin(low: int, high: int, value: int) -> QSpinBox:
    widget = QSpinBox()
    widget.setRange(low, high)
    widget.setValue(value)
    return widget


def button(text: str, action: Callable) -> QPushButton:
    widget = QPushButton(text)
    widget.clicked.connect(action)
    return widget


def row(*widgets: QWidget) -> QWidget:
    wrapper = QWidget()
    layout = QHBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    for widget in widgets:
        layout.addWidget(widget)
    return wrapper


def card(parent: QVBoxLayout, title: str) -> QFormLayout:
    frame = QFrame(objectName="card")
    form = QFormLayout(frame)
    form.setContentsMargins(15, 13, 15, 15)
    form.setSpacing(9)
    form.addRow(label(title, "heading"))
    parent.addWidget(frame)
    return form


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
        self.setWindowTitle("Karaoke Subtitle Engine")
        self.resize(1030, 800)
        self.setMinimumSize(710, 530)
        self.setStyleSheet(THEME)

        root = QWidget()
        self.setCentralWidget(root)
        shell = QVBoxLayout(root)
        shell.setContentsMargins(24, 18, 24, 18)
        shell.setSpacing(14)
        header = QHBoxLayout()
        header.addWidget(label("♫", "mark"))
        header.addWidget(label("Karaoke Subtitle Engine", "title"), 1)
        header.addWidget(label(f"v{__version__}"))
        header.addWidget(button("Settings", self.toggle_settings))
        shell.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        shell.addWidget(self.scroll, 1)
        content = QWidget()
        self.scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setSpacing(12)
        self.inputs = QWidget()
        layout.addWidget(self.inputs)
        inputs = QVBoxLayout(self.inputs)
        inputs.setContentsMargins(0, 0, 0, 0)
        inputs.setSpacing(12)
        self.make_settings(inputs)
        self.make_media(inputs)
        script = card(inputs, "Script")
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("Paste the exact words in the order they are spoken or sung.")
        self.editor.setMinimumHeight(146)
        self.editor.textChanged.connect(self.update_script)
        self.counter = label("0 words · 0 characters")
        self.language = QComboBox()
        for code, item in LANGUAGES.items():
            self.language.addItem(item.label, code)
        script.addRow(self.editor)
        script.addRow("Alignment language", self.language)
        script.addRow(self.counter)
        self.make_style(inputs)

        output = card(layout, "Output")
        self.output_label = label("A verified export will appear here.")
        self.output_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        output.addRow(self.output_label)
        self.output_controls = row(
            button("Play video", lambda: self.open_output("video")),
            button("Open folder", lambda: self.open_output("folder")),
            button("Alignment report", lambda: self.open_output("report")),
            button("Generate another", self.reset),
        )
        self.output_controls.setEnabled(False)
        output.addRow(self.output_controls)
        layout.addStretch()

        self.generate = button("Generate Karaoke Video", self.start_job)
        self.generate.setObjectName("generate")
        self.cancel_button = button("Cancel", self.cancel)
        self.cancel_button.setEnabled(False)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.status = label("Choose a video and enter its script.")
        shell.addWidget(self.status)
        shell.addWidget(row(self.generate, self.cancel_button, self.progress_bar))

    def make_settings(self, parent: QVBoxLayout) -> None:
        self.settings = QWidget()
        nested = QVBoxLayout(self.settings)
        nested.setContentsMargins(0, 0, 0, 0)
        form = card(nested, "Export settings")
        self.crf = spin(15, 29, 20)
        self.device = combo("CPU", "Auto · NVIDIA CUDA when available")
        self.save_ass = QCheckBox("Save ASS subtitles alongside the video")
        form.addRow("Encoding quality (CRF)", self.crf)
        form.addRow("Alignment device", self.device)
        form.addRow(self.save_ass)
        form.addRow(row(button("Open model folder", self.open_models),
                        button("Open diagnostic log", lambda: self.open_path(self.log_path))))
        parent.addWidget(self.settings)
        self.settings.hide()

    def toggle_settings(self) -> None:
        self.settings.setVisible(self.settings.isHidden())
        if not self.settings.isHidden():
            self.scroll.ensureWidgetVisible(self.settings)

    def make_media(self, parent: QVBoxLayout) -> None:
        form = card(parent, "Media")
        self.video_label = label("No video selected")
        self.audio_label = label("Use audio from video")
        self.folder_label = label("Same folder as the video")
        form.addRow(button("Choose video", lambda: self.choose_media(False)), self.video_label)
        form.addRow(row(button("Choose audio", lambda: self.choose_media(True)),
                        button("Use video audio", self.clear_audio)), self.audio_label)
        form.addRow(button("Output folder", self.choose_folder), self.folder_label)
        self.offset = QDoubleSpinBox()
        self.offset.setRange(-120, 120)
        self.offset.setDecimals(3)
        self.offset.setSingleStep(0.05)
        self.offset.setSuffix(" s")
        self.offset.setEnabled(False)
        self.offset.valueChanged.connect(self.update_sync)
        self.sync_hint = label("")
        form.addRow("Replacement audio offset", self.offset)
        form.addRow(self.sync_hint)
        self.update_sync()

    def make_style(self, parent: QVBoxLayout) -> None:
        form = card(parent, "Subtitle style")
        self.colors = Style()
        for font in FONT_DIR.glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(font))
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
        form.addRow("Size / words per line / margin", row(self.size, self.words, self.margin))
        form.addRow("Outline / shadow", row(self.stroke, self.shadow))
        form.addRow("Placement", row(self.horizontal, self.vertical))
        form.addRow("Colors", row(*(button(title, lambda key=key: self.choose_color(key))
                                   for title, key in (("Upcoming", "normal"), ("Active", "active"),
                                                      ("Completed", "completed"), ("Outline", "outline")))))
        self.preview = SubtitlePreview()
        form.addRow(self.preview)
        for control in (self.font, self.horizontal, self.vertical):
            control.currentIndexChanged.connect(self.update_preview)
        self.language.currentIndexChanged.connect(self.update_language)
        for control in (self.size, self.margin, self.stroke, self.shadow):
            control.valueChanged.connect(self.update_preview)
        self.update_preview()

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
        self.counter.setText(f"{len(script.split())} words · {len(script)} characters")

    @Slot()
    def update_sync(self) -> None:
        hint = "Positive values delay replacement audio. Negative values advance it."
        if self.video_info and self.audio_info:
            video, audio = self.video_info.video_duration, self.audio_info.audio_duration
            if video and audio:
                warning = duration_warning(video, audio, self.offset.value())
                if warning:
                    hint += "\n" + warning
        self.sync_hint.setText(hint)

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
                self.offset.setEnabled(True)
            else:
                self.video, self.video_info = path, info
                self.video_label.setText(f"{path.name} · {info.video_duration:.2f} s · "
                                         f"{info.width} × {info.height} · {info.fps:.2f} fps · "
                                         f"{info.video_codec} · {audio_desc}")
            self.update_sync()
            self.status.setText("Media ready.")

        self.start_task(inspect, accepted, "Inspecting media…", False)

    def clear_audio(self) -> None:
        self.audio = self.audio_info = None
        self.offset.setValue(0)
        self.offset.setEnabled(False)
        self.audio_label.setText("Use audio from video")
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
                          self.subtitle_style(), self.offset.value(), self.crf.value(),
                          self.save_ass.isChecked(), "cpu" if self.device.currentIndex() == 0 else "auto")
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
            return Job(self.aligner).run(project, cancel, update)

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
        self.status.setText(status)
        self.progress_bar.setRange(0, 0)
        self.inputs.setEnabled(False)
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
        self.inputs.setEnabled(True)
        self.generate.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)

    @Slot(int, str)
    def show_progress(self, percent: int, text: str) -> None:
        self.status.setText(text)
        self.progress_bar.setRange(0, 0 if percent < 0 else 100)
        if percent >= 0:
            self.progress_bar.setValue(percent)

    @Slot()
    def cancel(self) -> None:
        if self.worker:
            self.worker.cancel.event.set()
            self.cancel_button.setEnabled(False)
            self.status.setText("Cancelling after the current processing step…")

    @Slot(str)
    def error(self, message: str) -> None:
        self.status.setText(message)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

    def show_output(self, result: Result) -> None:
        self.output = result
        detail = "\n".join(result.issues[:8])
        if len(result.issues) > 8:
            detail += f"\n{len(result.issues) - 8} more entries in the alignment report."
        self.output_label.setText(str(result.video) + ("\n\n" + detail if detail else ""))
        self.output_controls.setEnabled(True)
        self.status.setText("Video exported. Review the alignment report." if result.issues else "Video exported.")
        self.scroll.ensureWidgetVisible(self.output_label)

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
        self.folder_label.setText("Same folder as the video")
        self.clear_audio()
        self.editor.clear()
        self.output_controls.setEnabled(False)
        self.output_label.setText("A verified export will appear here.")
        self.progress_bar.setValue(0)
        self.status.setText("Choose a video and enter its script.")
        self.editor.setFocus()

    def closeEvent(self, event) -> None:
        if self.thread:
            self.close_pending = True
            self.cancel()
            event.ignore()
        else:
            event.accept()
