"""Pixel and font-selection checks through the same Windows FFmpeg used for delivery."""
from dataclasses import replace
import json
import subprocess

import numpy as np
import pytest
from PySide6.QtGui import QImage

from app.core import Cancellation, EngineError, Project, Word
from app.font_library import HINDI, stage_fonts
from app.jobs import Job
from app.media import ASS_FILTER, Media
from app.presets import BUILTINS, DEFAULT
from app.preview import render_frame
from app.styles import shaped_font

DISPLAY = ("ज़िंदगी उम्मीद ख़ूबसूरत नमस्ते धन्यवाद क्या पता हमेशा मुस्कुराती परिस्थितियाँ "
           "प्रेम और विश्वास क्षत्रिय र्क र्‍यो हँसी दुःख १२३, प्रकाश। Music")
SPOKEN = DISPLAY.replace("Music", "संगीत")


class TimedFixture:
    calls = 0

    def align(self, wav, tokens, language, device, cancel, status):
        self.calls += 1
        return [Word(token, i * .4, i * .4 + .36, .93) for i, token in enumerate(tokens)]


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    try:
        media = Media()
    except EngineError as exc:
        pytest.skip(str(exc))
    path = tmp_path_factory.mktemp("studio-media") / "स्टूडियो, 'clip'.mp4"
    subprocess.run([media.ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=0x28394A:s=920x518:r=25",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", "8.6", "-c:v", "libx264",
                    "-c:a", "aac", str(path)], check=True)
    return media, path


def pixels(data):
    img = QImage.fromData(data, "PNG").convertToFormat(QImage.Format.Format_RGB888)
    assert not img.isNull()
    return np.array(np.frombuffer(img.bits(), np.uint8).reshape(img.height(), img.bytesPerLine())
                    [:, :img.width() * 3].reshape(img.height(), img.width(), 3), dtype=np.int16)


def decode(media, path, t):
    return subprocess.check_output([media.ffmpeg, "-v", "error", "-ss", str(t), "-i", str(path),
                                    "-frames:v", "1", "-c:v", "png", "-f", "image2pipe", "-"])


@pytest.mark.parametrize("family,preset", list(zip(HINDI, ("Clean Reel", DEFAULT, "Mixed Typography",
                                                          DEFAULT, "Poetry / Shayari"), strict=True)))
def test_studio_export_preview_and_faces(source, tmp_path, family, preset):
    media, source_video = source
    style = replace(BUILTINS[preset], hindi_font=family, hi_italic=family.startswith("Tiro"),
                    en_italic=True, en_weight=600, size=90, words_per_line=4, background=True)
    project = Project(source_video, None, SPOKEN, "hi", tmp_path, style,
                      export_ass=True, display_script=DISPLAY)
    job = Job(TimedFixture(), media)
    result = job.run(project, Cancellation(), lambda *_: None)
    report = json.loads(result.report.read_text(encoding="utf-8"))
    assert [row["text"] for row in report["words"]] == SPOKEN.split()
    assert [row["video_start"] for row in report["words"]] == [i * .4 for i in range(len(SPOKEN.split()))]
    ass = result.ass.read_text(encoding="utf-8")
    for word in DISPLAY.split():
        assert word in ass
    work = tmp_path / "sample"
    work.mkdir()
    info = media.probe(source_video, Cancellation())
    preview = pixels(render_frame(work, source_video, info, style, DISPLAY, Cancellation()))
    native = decode(media, result.video, .52)
    (tmp_path / "decoded.png").write_bytes(native)
    exported = pixels(native)
    assert preview.shape == exported.shape
    difference = np.abs(exported - pixels(decode(media, source_video, .52))).max(axis=2)
    ink = difference > 60
    assert ink.sum() > 300
    assert np.where(ink)[0].min() > 320
    assert np.abs(exported - preview)[ink].mean() < 15

    # Inspect the actual renderer's decisions, including the final mixed-script phrase.
    (work / "captions.ass").write_text(ass, encoding="utf-8")
    stage_fonts(work)
    log = subprocess.run([media.ffmpeg, "-hide_banner", "-loglevel", "verbose", "-i", str(source_video),
                          "-vf", ASS_FILTER, "-an", "-f", "null", "-"], cwd=work, check=True,
                         capture_output=True).stderr.decode("utf-8", "replace")
    selections = [line for line in log.splitlines() if "fontselect:" in line]
    for face in style.faces:
        postscript = shaped_font(face).face.get_name(6)
        assert any(line.endswith(", " + postscript) for line in selections), selections
    assert "failed to find any fallback" not in log.lower()
    assert "harfbuzz" in log.lower()
    if preset == DEFAULT:
        first = pixels(decode(media, result.video, .12))
        assert np.abs(first - exported).max(axis=2).sum() > 30000


def test_restyle_reuses_alignment_and_preserves_report(source, tmp_path):
    media, video = source
    aligner = TimedFixture()
    job = Job(aligner, media)
    project = Project(video, None, "Every word", "en", tmp_path, BUILTINS[DEFAULT])
    first = job.run(project, Cancellation(), lambda *_: None)
    second = job.run(replace(project, style=BUILTINS["Mixed Typography"], display_script="हर word"),
                     Cancellation(), lambda *_: None)
    assert aligner.calls == 1 and first.report.read_bytes() == second.report.read_bytes()
    assert decode(media, first.video, .52) != decode(media, second.video, .52)
    with pytest.raises(EngineError, match="one word"):
        replace(project, display_script="one two three").validate()


def test_all_26_static_faces_selected_by_libass(source, tmp_path):
    from app.font_library import all_faces
    from app.subtitles import generate_ass
    from app.core import tokenize

    media, video = source
    captions = []
    for index, face in enumerate(all_faces()):
        is_hindi = face.family in HINDI
        attributes = ({"hindi_font": face.family, "hi_weight": face.weight, "hi_italic": face.italic}
                      if is_hindi else {"font": face.family, "en_weight": face.weight, "en_italic": face.italic})
        style = replace(BUILTINS[DEFAULT], **attributes)
        word = Word(tokenize("क्षत्रिय" if is_hindi else "Studio")[0], index / 5, (index + 1) / 5)
        header, _, events = generate_ass([word], style, 920, 518).partition("Dialogue:")
        captions.append("Dialogue:" + events)
    (tmp_path / "captions.ass").write_text(header + "".join(captions), encoding="utf-8")
    stage_fonts(tmp_path)
    log = subprocess.run([media.ffmpeg, "-hide_banner", "-i", str(video), "-vf", ASS_FILTER, "-an",
                          "-f", "null", "-"], cwd=tmp_path, check=True, capture_output=True).stderr
    selected = {line.rsplit(", ", 1)[-1] for line in log.decode("utf-8", "replace").splitlines()
                if "fontselect:" in line}
    assert {shaped_font(f).face.get_name(6) for f in all_faces()} <= selected


def test_colors_effects_and_anchor_pixels(source, tmp_path):
    media, video = source
    cancel = Cancellation()
    info = media.probe(video, cancel)
    style = replace(BUILTINS["Mixed Typography"], size=108, vertical=6, horizontal=1,
                    hi_color="#FF0000", en_color="#00FF00", outline="#FFFF00", stroke=7,
                    shadow=9, shadow_color="#FF00FF", shadow_opacity=100,
                    background=True, box_color="#0000FF", box_opacity=100)
    def sample(style):
        return pixels(render_frame(tmp_path, video, info, style, "उम्मीद Hello", cancel))
    bright = sample(style)
    for rgb in ((255, 0, 0), (0, 255, 0), (255, 255, 0), (255, 0, 255), (0, 0, 255)):
        matches = (np.abs(bright - rgb).max(axis=2) < 36)
        assert matches.sum() > 8
        y, x = np.where(matches)
        assert y.max() < 180 and x.max() < 500
    transparent = sample(replace(style, box_opacity=0, shadow_enabled=False, outline_enabled=False))
    assert not (np.abs(transparent - [0, 0, 255]).max(axis=2) < 36).any()
    other = sample(replace(style, horizontal=3, vertical=0))
    y, x = np.where(np.abs(other - [255, 0, 0]).max(axis=2) < 36)
    assert y.min() > 325 and x.min() > 450


@pytest.mark.model
@pytest.mark.parametrize("language,preset", [("en", DEFAULT), ("hi", "Poetry / Shayari")])
def test_real_alignment_with_studio_export(tmp_path, language, preset):
    import os
    from pathlib import Path
    from app.alignment import Wav2VecAligner, cache_dir

    wave = os.getenv(f"KARAOKE_TEST_{language.upper()}_WAV")
    script = os.getenv(f"KARAOKE_TEST_{language.upper()}_SCRIPT")
    if not (wave and script):
        pytest.skip("Set matching acoustic-model fixture WAV and SCRIPT.")
    media = Media()
    video = tmp_path / "voice.mp4"
    subprocess.run([media.ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=0x28394A:s=640x360:r=25",
                    "-i", wave, "-c:v", "libx264", "-c:a", "aac", "-shortest", str(video)], check=True)
    model = Wav2VecAligner(Path(os.getenv("KARAOKE_TEST_MODELS", cache_dir() / "models")))
    project = Project(video, None, script, language, tmp_path, BUILTINS[preset], export_ass=True)
    result = Job(model, media).run(project, Cancellation(), lambda *_: None)
    words = json.loads(result.report.read_text(encoding="utf-8"))["words"]
    assert [w["text"] for w in words] == script.split()
    assert all(0 <= w["audio_start"] < w["audio_end"] for w in words)
    t = (words[0]["video_start"] + words[0]["video_end"]) / 2
    changed = np.abs(pixels(decode(media, result.video, t)) - pixels(decode(media, video, t))).max(axis=2)
    assert (changed > 70).sum() > 40
