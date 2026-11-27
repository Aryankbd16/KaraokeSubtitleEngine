from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from .core import Cancellation, Cancelled, EngineError, Style, Word, tokenize
from .font_library import stage_fonts
from .media import ASS_FILTER, Media
from .subtitles import generate_ass
from .widgets import make_label, set_prop


class SubtitlePreview(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.style = Style()
        self.words = ("Every", "word", "shines")
        self.setMinimumHeight(138)
        self.setAccessibleName("Subtitle style preview")

    def show_style(self, style: Style, words: tuple[str, str, str]) -> None:
        self.style = style
        self.words = words
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor("#283348")))
        painter.setBrush(QColor("#090C12"))
        painter.drawRoundedRect(area, 8, 8)

        # Subtle title-safe frame indicator
        safe = area.adjusted(10, 10, -10, -10)
        safe_pen = QPen(QColor(255, 255, 255, 16))
        safe_pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(safe_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(safe, 4, 4)

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


def render_frame(work, video, info, style, sample, cancel):
    """Cache one source frame for the dialog lifetime. The sample clock is independent of seek time."""
    media = Media()
    frame = work / "source.mkv"
    size = info.display_size if info else (960, 540)
    if video and info and not frame.exists():
        # Decode one native-resolution frame, including the video's display rotation.
        for seconds in (min(30, (info.video_duration or 0) * .35), 0):
            try:
                media.run([media.ffmpeg, "-v", "error", "-y", "-abort_on", "empty_output", "-ss", str(seconds),
                           "-i", str(video.resolve()), "-map", "0:V:0", "-frames:v", "1", "-c:v", "ffv1",
                           "source.tmp.mkv"], cancel, cwd=work)
            except Cancelled:
                raise
            except EngineError:
                if seconds == 0:
                    raise
                continue
            pending = work / "source.tmp.mkv"
            if pending.exists() and pending.stat().st_size:
                pending.replace(frame)
                break
        if not frame.exists():
            raise EngineError("No preview frame could be decoded from this video.")
    source = ["-i", frame.name] if frame.exists() else ["-f", "lavfi", "-i", "color=0x263344:s=960x540"]
    words = [Word(token, i * .4, i * .4 + .36) for i, token in enumerate(tokenize(sample))]
    (work / "captions.ass").write_text(generate_ass(words, style, *size), encoding="utf-8")
    stage_fonts(work, style.faces)
    # Apply ASS at source resolution before fitting the still into the preview panel.
    ratio = size[0] / size[1]
    h = max(1, round(min(540, 920 / ratio)))
    w = max(1, round(h * ratio))
    timestamp = .52 if len(words) > 1 else .12
    return media.run([media.ffmpeg, "-v", "error", *source, "-frames:v", "1", "-vf",
                      f"setpts=PTS-STARTPTS+{timestamp}/TB,{ASS_FILTER},scale={w}:{h},setsar=1",
                      "-c:v", "png", "-f", "image2pipe", "-"], cancel, cwd=work)


class FramePreview(QWidget):
    def __init__(self, video, info):
        super().__init__()
        self.video, self.info = video, info
        self.picture = QLabel("Preparing preview…")
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.picture.setMinimumSize(200, 160)
        self.picture.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.picture.setStyleSheet("color: #8B97AF; background: transparent;")

        self.status = make_label("", role="hint")
        size = info.display_size if info else (960, 540)
        self.dimensions = make_label(f"{size[0]} × {size[1]}", role="mono", wrap=False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 2)
        layout.setSpacing(8)
        layout.addWidget(self.picture, 1)

        meta = QHBoxLayout()
        meta.setContentsMargins(4, 0, 4, 2)
        meta.setSpacing(10)
        meta.addWidget(self.status, 1)
        meta.addWidget(self.dimensions)
        layout.addLayout(meta)

        self.original = QPixmap()
        self.directory = TemporaryDirectory(prefix="karaoke-preview-")
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.future = self.cancel = self.pending = None
        self.timer = QTimer(self, singleShot=True, interval=220)
        self.timer.timeout.connect(self.start)
        self.poll = QTimer(self, interval=40)
        self.poll.timeout.connect(self.finish)

    def request(self, style, sample):
        self.pending = style, sample
        if self.cancel:
            self.cancel.event.set()
        self.timer.start()

    def start(self):
        if self.future or self.pending is None:
            return
        style, sample = self.pending
        self.pending = None
        self.cancel = Cancellation()
        self.future = self.pool.submit(render_frame, Path(self.directory.name), self.video, self.info,
                                       style, sample, self.cancel)
        self.status.setText("Rendering sample…")
        set_prop(self.status, "tone", "muted")
        self.poll.start()

    def finish(self):
        if not self.future.done():
            return
        self.poll.stop()
        try:
            data = self.future.result()
            if self.pending is None:
                pixmap = QPixmap()
                if not pixmap.loadFromData(data, "PNG"):
                    raise EngineError("FFmpeg returned an unreadable preview.")
                self.original = pixmap
                self.fit()
                self.status.setText("Selected video" if self.video else "Sample background")
                set_prop(self.status, "tone", "success" if self.video else "muted")
        except Cancelled:
            pass
        except Exception as exc:
            self.status.setText(f"Preview unavailable. {exc}")
            set_prop(self.status, "tone", "warning")
        self.future = self.cancel = None
        if not self.timer.isActive():
            self.start()

    def fit(self):
        if not self.original.isNull():
            self.picture.setPixmap(self.original.scaled(self.picture.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                        Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit()

    def shutdown(self):
        self.timer.stop()
        self.poll.stop()
        if self.cancel:
            self.cancel.event.set()
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.directory.cleanup()
