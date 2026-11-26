import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

from app.alignment import Wav2VecAligner, cache_dir
from app.core import Cancellation, EngineError, Project, Style, Word
from app.jobs import Job
from app.media import Media


@pytest.fixture
def media():
    try:
        return Media()
    except EngineError as exc:
        pytest.skip(str(exc))


def ffmpeg(media, *args):
    return subprocess.check_output([media.ffmpeg, "-v", "error", *map(str, args)])


@pytest.fixture
def sample(media, tmp_path):
    video = tmp_path / "Video नाम.mp4"
    replacement = tmp_path / "Voice नाम.wav"
    ffmpeg(media, "-f", "lavfi", "-i", "color=c=0x152034:s=640x360:r=25:d=2",
           "-f", "lavfi", "-i", "sine=f=440:r=48000:d=2",
           "-c:v", "libx264", "-c:a", "aac", video)
    ffmpeg(media, "-f", "lavfi", "-i", "sine=f=810:r=48000:d=1.7",
           "-af", "adelay=14400S", replacement)
    return video, replacement


class FixtureAligner:
    def align(self, audio, tokens, language, device, cancel, status):
        assert audio.is_file()
        status("Controlled alignment fixture")
        return [Word(tokens[0], 0.2, 0.55, 0.95), Word(tokens[1], 0.7, 1.3, 0.9)]


def frame(media, video, time):
    data = ffmpeg(media, "-ss", time, "-i", video, "-frames:v", 1, "-an",
                  "-pix_fmt", "rgb24", "-f", "rawvideo", "-")
    return np.frombuffer(data, dtype=np.uint8).reshape(360, 640, 3)


@pytest.mark.parametrize("audio_kind,offset", [("embedded", 0), ("replacement", 0.4), ("replacement", -0.1)])
def test_render_paths(media, sample, tmp_path, audio_kind, offset):
    video, replacement = sample
    audio = replacement if audio_kind == "replacement" else None
    status = []
    style = Style(font="Noto Sans Devanagari", size=72)
    output = Job(FixtureAligner(), media).run(
        Project(video, audio, "नमस्ते दुनिया।", "hi", tmp_path, style, offset, export_ass=True),
        Cancellation(), lambda *progress: status.append(progress),
    )
    assert output.video != video
    assert output.ass and "नमस्ते" in output.ass.read_text(encoding="utf-8")
    assert status[-1][0] == 100
    report = json.loads(output.report.read_text(encoding="utf-8"))
    assert report["words"][0]["video_start"] == pytest.approx(0.2 + offset)
    info = media.probe(output.video, Cancellation())
    assert info.video_duration == pytest.approx(2, abs=0.05)
    assert info.audio_codec == "aac"
    image = frame(media, output.video, 0.35 + offset)
    yellow = (image[:, :, 0] > 185) & (image[:, :, 1] > 150) & (image[:, :, 2] < 145)
    assert yellow.sum() > 20
    assert np.flatnonzero(yellow.any(axis=1)).min() > 250
    raw = ffmpeg(media, "-i", output.video, "-vn", "-ac", 1, "-ar", 48000, "-f", "f32le", "-")
    pcm = np.frombuffer(raw, dtype="<f4")
    if audio:
        onset = 0.3 + offset
        assert np.max(np.abs(pcm[:int((onset - 0.025) * 48000)])) < 0.005
        assert np.max(np.abs(pcm[int((onset + 0.025) * 48000):int((onset + 0.05) * 48000)])) > 0.05
    block = pcm[38400:48000]
    frequency = np.argmax(np.abs(np.fft.rfft(block))) * 48000 / len(block)
    assert frequency == pytest.approx(810 if audio else 440, abs=5)
    assert not list(tmp_path.glob(".karaoke-*"))


def test_job_cleanup_on_failure(media, sample, tmp_path):
    class FailedAligner:
        def align(self, *_):
            raise EngineError("Controlled alignment failure")

    with pytest.raises(EngineError, match="Controlled"):
        Job(FailedAligner(), media).run(
            Project(sample[0], None, "Hello world", "en", tmp_path), Cancellation(), lambda *_: None)
    assert not list(tmp_path.glob(".karaoke-*"))
    assert not list(tmp_path.glob("*_karaoke*"))


@pytest.mark.model
@pytest.mark.parametrize("language", ["en", "hi"])
def test_real_model_end_to_end(media, tmp_path, language):
    source = os.getenv(f"KARAOKE_TEST_{language.upper()}_WAV")
    script = os.getenv(f"KARAOKE_TEST_{language.upper()}_SCRIPT")
    if not source or not script:
        pytest.skip(f"Set KARAOKE_TEST_{language.upper()}_WAV and matching SCRIPT to run a real model.")
    source = Path(source).resolve()
    video = tmp_path / "speech.mp4"
    ffmpeg(media, "-f", "lavfi", "-i", "color=c=0x152034:s=640x360:r=25", "-i", source,
           "-c:v", "libx264", "-c:a", "aac", "-shortest", video)
    cache = Path(os.getenv("KARAOKE_TEST_MODELS", str(cache_dir() / "models")))
    aligner = Wav2VecAligner(cache)
    result = Job(aligner, media).run(
        Project(video, None, script, language, tmp_path,
                Style(font="Noto Sans Devanagari") if language == "hi" else Style(), export_ass=True),
        Cancellation(), lambda _, stage: print(stage, flush=True))
    report = json.loads(result.report.read_text(encoding="utf-8"))
    print(json.dumps(report, ensure_ascii=False))
    assert len(report["words"]) == len(script.split())
    assert all(0 <= word["audio_start"] < word["audio_end"] <= report["input_audio_duration"] + 0.05
               for word in report["words"])
    assert result.video.is_file()
