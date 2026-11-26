from __future__ import annotations

import json
import logging
import math
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Callable

from .core import Cancellation, EngineError
from .font_library import stage_fonts

LOG = logging.getLogger(__name__)
ASS_FILTER = "ass=captions.ass:fontsdir=fonts:shaping=complex"


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    video_duration: float | None
    audio_duration: float | None
    width: int = 0
    height: int = 0
    fps: float = 0
    video_codec: str = ""
    audio_codec: str = ""
    sample_rate: int = 0
    channels: int = 0
    video_start: float = 0
    audio_start: float = 0
    sample_aspect: float = 1
    rotation: int = 0

    @property
    def display_size(self) -> tuple[int, int]:
        width = max(1, round(self.width * self.sample_aspect))
        return (self.height, width) if self.rotation % 180 == 90 else (width, self.height)


def parse_probe(data: dict) -> MediaInfo:
    streams = data.get("streams", [])
    video = next((s for s in streams if s["codec_type"] == "video"
                  and not s.get("disposition", {}).get("attached_pic")), {})
    audio = next((s for s in streams if s["codec_type"] == "audio"), {})
    container = data.get("format", {})

    def number(value: object, fallback: float = 0) -> float:
        try:
            out = float(str(value))
        except (ValueError, TypeError):
            return fallback
        return out if math.isfinite(out) else fallback

    start = number(container.get("start_time"))
    duration = number(container.get("duration"))
    video_start = number(video.get("start_time"), start)
    audio_start = number(audio.get("start_time"), start)

    def stream_duration(stream: dict, stream_start: float) -> float | None:
        if not stream:
            return None
        direct = number(stream.get("duration"))
        if direct > 0:
            return direct
        tag = stream.get("tags", {}).get("DURATION", "")
        parts = tag.split(":")
        if len(parts) == 3:
            tagged = number(parts[0]) * 3600 + number(parts[1]) * 60 + number(parts[2])
            if tagged > 0:
                return tagged
        return duration + start - stream_start

    try:
        fps = float(Fraction(video.get("avg_frame_rate", "0")))
    except (TypeError, ValueError, ZeroDivisionError):
        fps = 0
    try:
        sample_aspect = float(Fraction(video.get("sample_aspect_ratio", "1:1").replace(":", "/")))
    except (AttributeError, ValueError, ZeroDivisionError):
        sample_aspect = 1
    rotation = next((round(number(entry.get("rotation"))) for entry in video.get("side_data_list", [])
                     if "rotation" in entry), 0)
    return MediaInfo(
        duration,
        stream_duration(video, video_start), stream_duration(audio, audio_start),
        int(video.get("width", 0)), int(video.get("height", 0)), fps,
        video.get("codec_name", ""), audio.get("codec_name", ""),
        int(number(audio.get("sample_rate"))), int(number(audio.get("channels"))),
        video_start, audio_start, sample_aspect if sample_aspect > 0 else 1, rotation,
    )


def duration_warning(video: float, audio: float, offset: float) -> str | None:
    difference = audio + offset - video
    if abs(difference) > max(1, video * 0.05):
        return (f"Replacement audio ends {abs(difference):.1f} seconds "
                f"{'after' if difference > 0 else 'before'} the video. "
                "The export follows the video duration.")
    return None


class Media:
    def __init__(self, ffmpeg: str | None = None, ffprobe: str | None = None) -> None:
        self.ffmpeg = self._tool("ffmpeg", ffmpeg)
        self.ffprobe = self._tool("ffprobe", ffprobe)

    @staticmethod
    def _tool(name: str, override: str | None) -> str:
        value = override or os.getenv(f"KARAOKE_{name.upper()}") or shutil.which(name)
        if not value:
            raise EngineError(f"{name} was not found. Install FFmpeg and add its bin folder to PATH.")
        candidate = Path(value)
        return str(candidate.resolve()) if candidate.exists() else value

    @staticmethod
    def run(args: list[str], cancel: Cancellation, *, cwd: Path | None = None,
            timeout: float = 90, progress: Callable[[float], None] | None = None) -> bytes:
        cancel.check()
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            try:
                process = subprocess.Popen(args, cwd=cwd, stdin=subprocess.DEVNULL,
                                           stdout=stdout, stderr=stderr, creationflags=flags)
            except OSError as exc:
                raise EngineError("Could not start the FFmpeg tool. Check its installation.") from exc
            deadline = time.monotonic() + timeout
            position = 0
            pending = b""
            try:
                while process.poll() is None:
                    if cancel.event.wait(0.15):
                        cancel.check()
                    if time.monotonic() > deadline:
                        raise EngineError("FFmpeg timed out.")
                    if progress and cwd:
                        path = cwd / "progress.txt"
                        if path.exists():
                            with path.open("rb") as status:
                                status.seek(position)
                                chunks = (pending + status.read()).split(b"\n")
                                position = status.tell()
                            pending = chunks.pop()
                            for line in chunks:
                                if line.startswith(b"out_time_us="):
                                    value = line.split(b"=", 1)[1].strip()
                                    if value.lstrip(b"-").isdigit():
                                        progress(int(value) / 1_000_000)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
            if process.returncode:
                stderr.seek(max(0, stderr.tell() - 3000))
                details = stderr.read().decode("utf-8", errors="replace").strip()
                for argument in args:
                    if os.path.isabs(argument):
                        details = details.replace(argument, Path(argument).name)
                LOG.error("FFmpeg tool exited %s: %s", process.returncode, details)
                tail = details.splitlines()[-1] if details else "See the application log."
                raise EngineError(f"Media processing failed. {tail}")
            stdout.seek(0)
            return stdout.read()

    def probe(self, path: Path, cancel: Cancellation) -> MediaInfo:
        if not path.is_file() or not path.stat().st_size:
            raise EngineError(f"Media file is missing or empty: {path.name}")
        raw = self.run([self.ffprobe, "-v", "error", "-show_format", "-show_streams",
                        "-of", "json", str(path.resolve())], cancel)
        try:
            return parse_probe(json.loads(raw))
        except (ValueError, KeyError, TypeError) as exc:
            raise EngineError("Could not interpret the media metadata.") from exc

    def extract(self, path: Path, destination: Path, duration: float, cancel: Cancellation) -> None:
        self.run([self.ffmpeg, "-v", "error", "-i", str(path.resolve()), "-map", "0:a:0",
                  "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(destination)],
                 cancel, timeout=max(120, duration * 3))

    def render(self, video: Path, audio: Path | None, offset: float, duration: float,
               crf: int, work: Path, cancel: Cancellation,
               progress: Callable[[float], None]) -> Path:
        audio_chain = "asetpts=PTS-STARTPTS"
        if offset > 0:
            audio_chain += f",adelay={round(offset * 48000)}S:all=1"
        elif offset < 0:
            audio_chain += f",atrim=start={-offset:.9f},asetpts=PTS-STARTPTS"
        audio_chain = "aresample=48000," + audio_chain + f",apad,atrim=duration={duration:.9f}"
        self.run([self.ffmpeg, "-v", "error", "-i", str((audio or video).resolve()),
                  "-map", "0:a:0", "-af", audio_chain, "-t", f"{duration:.9f}",
                  "-c:a", "aac", "-q:a", "2", "track.m4a"],
                 cancel, cwd=work, timeout=max(120, duration * 3))
        stage_fonts(work)
        args = [self.ffmpeg, "-v", "error", "-nostats", "-progress", "progress.txt",
                "-i", str(video.resolve()), "-map", "0:V:0",
                "-vf", f"setpts=PTS-STARTPTS,{ASS_FILTER},"
                "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                "-t", f"{duration:.9f}", "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                "-pix_fmt", "yuv420p", "picture.mp4"]
        self.run(args, cancel, cwd=work, timeout=max(600, duration * 60), progress=progress)
        self.run([self.ffmpeg, "-v", "error", "-i", "picture.mp4", "-i", "track.m4a",
                  "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-movflags", "+faststart",
                  "render.mp4"], cancel, cwd=work, timeout=max(120, duration * 3))
        output = work / "render.mp4"
        info = self.probe(output, cancel)
        tolerance = max(0.15, 2 / info.fps if info.fps else 0.25)
        if (info.video_codec != "h264" or info.audio_codec != "aac"
                or info.video_duration is None or info.audio_duration is None
                or abs(info.video_duration - duration) > tolerance
                or abs(info.audio_duration - duration) > tolerance):
            raise EngineError("The rendered MP4 failed stream or duration validation.")
        return output
