from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from .alignment import Aligner, LANGUAGES, check_language
from .core import Cancellation, EngineError, Project, presentation
from .media import Media, duration_warning
from .subtitles import centiseconds, generate_ass


@dataclass(frozen=True)
class Result:
    video: Path
    report: Path
    ass: Path | None
    issues: tuple[str, ...]


def publish(folder: Path, stem: str, artifacts: dict[str, Path]) -> dict[str, Path]:
    for number in range(1, 10000):
        root = f"{stem[:150]}_karaoke" + (f"_{number}" if number > 1 else "")
        paths = {suffix: folder / f"{root}{suffix}" for suffix in artifacts}
        owned: list[Path] = []
        try:
            for path in paths.values():
                with path.open("xb"):
                    owned.append(path)
            for suffix, path in paths.items():
                os.replace(artifacts[suffix], path)
        except FileExistsError:
            for path in owned:
                path.unlink(missing_ok=True)
            continue
        except OSError as exc:
            for path in owned:
                path.unlink(missing_ok=True)
            raise EngineError("Could not write the output files. Check folder permissions and space.") from exc
        return paths
    raise EngineError("Could not find an available output name.")


class Job:
    def __init__(self, aligner: Aligner, media: Media | None = None) -> None:
        self.aligner = aligner
        self.media = media or Media()

    def run(self, project: Project, cancel: Cancellation,
            progress: Callable[[int, str], None]) -> Result:
        tokens = project.validate()
        check_language(project.language, tokens)
        progress(5, "Inspecting media")
        video = self.media.probe(project.video, cancel)
        if not video.video_duration or video.video_duration <= 0 or not video.width or not video.height:
            raise EngineError("The selected file has no usable video stream or duration.")
        source = project.audio or project.video
        audio = self.media.probe(source, cancel) if project.audio else video
        if not audio.audio_duration or audio.audio_duration <= 0 or not audio.channels:
            raise EngineError("The selected source has no usable audio stream.")
        offset = project.offset if project.audio else video.audio_start - video.video_start
        duration = video.video_duration
        if offset >= duration or offset + audio.audio_duration <= 0:
            raise EngineError("The audio falls entirely outside the video at this offset.")
        warning = duration_warning(duration, audio.audio_duration, offset) if project.audio else None
        if shutil.disk_usage(project.output_dir).free < max(64 * 1024**2, audio.audio_duration * 32000):
            raise EngineError("Free more disk space in the output folder before processing.")
        try:
            directory = TemporaryDirectory(prefix=".karaoke-", dir=project.output_dir.resolve())
        except OSError as exc:
            raise EngineError("The selected output folder is not writable.") from exc
        with directory as work_directory:
            work = Path(work_directory)
            progress(15, "Preparing alignment audio")
            wav = work / "alignment.wav"
            self.media.extract(source, wav, audio.audio_duration, cancel)
            if warning:
                progress(25, warning)
            aligned = self.aligner.align(wav, tokens, project.language, project.device,
                                         cancel, lambda msg: progress(-1, msg))
            cancel.check()
            words = presentation(aligned, offset, duration)
            if not any(w.start is not None and w.end is not None
                       and centiseconds(w.start) < centiseconds(w.end) for w in words):
                raise EngineError("No words could be highlighted within the video. Check the script, "
                                  "language, audio quality and offset.")
            progress(65, "Building karaoke captions")
            captions = work / "captions.ass"
            captions.write_text(generate_ass(words, project.style, *video.display_size),
                                encoding="utf-8")
            report = work / "alignment.json"
            issues = [f"{word.token.text}: {word.issue}" for word in words if word.issue]
            report.write_text(json.dumps({
                "provider": type(self.aligner).__name__,
                "language": project.language,
                "model": LANGUAGES[project.language].model,
                "offset_seconds": offset,
                "video_duration": duration,
                "input_audio_duration": audio.audio_duration,
                "duration_warning": warning,
                "words": [{"text": raw.token.text, "normalized": raw.token.normalized,
                           "audio_start": raw.start, "audio_end": raw.end,
                           "video_start": shown.start, "video_end": shown.end,
                           "score": raw.score, "alignment_issue": raw.issue, "issue": shown.issue}
                          for raw, shown in zip(aligned, words, strict=True)],
            }, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
            progress(70, "Rendering karaoke video")
            rendered = self.media.render(
                project.video, project.audio, offset, duration, project.crf, work, cancel,
                lambda seconds: progress(min(98, 70 + int(max(0, seconds) / duration * 28)),
                                         "Rendering karaoke video")
            )
            cancel.check()
            artifacts = {".alignment.json": report}
            if project.export_ass:
                artifacts[".ass"] = captions
            artifacts[".mp4"] = rendered
            output = publish(project.output_dir, project.video.stem, artifacts)
            progress(100, "Output verified")
            if warning:
                issues.insert(0, warning)
            return Result(output[".mp4"], output[".alignment.json"], output.get(".ass"), tuple(issues))
