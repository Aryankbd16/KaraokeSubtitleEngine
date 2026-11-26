import json
from dataclasses import replace

import numpy as np
import pytest

from app.alignment import align_emissions, check_language, ctc_path
from app.core import (
    VIDEO, Cancellation, Cancelled, EngineError, Project, Style, Word, presentation,
    tokenize, validate_file, validate_words,
)
from app.jobs import publish
from app.media import duration_warning, parse_probe
from app.subtitles import ass_time, centiseconds, generate_ass, phrases


def test_file_validation(tmp_path):
    source = tmp_path / "नाम test.MP4"
    with pytest.raises(EngineError, match="Cannot read"):
        validate_file(source, VIDEO)
    source.touch()
    with pytest.raises(EngineError, match="empty"):
        validate_file(source, VIDEO)
    source.write_bytes(b"probe is a separate step")
    validate_file(source, VIDEO)
    with pytest.raises(EngineError, match="supported"):
        validate_file(source.with_suffix(".exe"), VIDEO)
    with pytest.raises(EngineError, match="offset"):
        Project(source, None, "Word", "en", tmp_path, offset=1).validate()


@pytest.mark.parametrize("script", ["", " \n\t", "। …"])
def test_empty_script(script):
    with pytest.raises(EngineError, match="script"):
        tokenize(script)


def test_display_mapping_and_languages():
    words = tokenize("  Ｈello,  DON’T!\nnext\n\n  हिन्दी है।")
    assert [word.text for word in words] == ["Ｈello,", "DON’T!", "next", "हिन्दी", "है।"]
    assert [word.normalized for word in words] == ["hello", "don't", "next", "हिन्दी", "है"]
    assert words[3].paragraph
    check_language("en", tokenize("Word."))
    check_language("hi", tokenize("नमस्ते दुनिया।"))
    with pytest.raises(EngineError, match="Romanized"):
        check_language("hi", tokenize("namaste duniya"))
    with pytest.raises(EngineError, match="mixed"):
        check_language("en", tokenize("hello दुनिया"))
    with pytest.raises(EngineError, match="Choose"):
        check_language("fr", tokenize("bonjour"))


def test_probe_metadata():
    data = json.loads('''{"format":{"duration":"15","start_time":"1"},
        "streams":[{"codec_type":"video","disposition":{"attached_pic":1}},
        {"codec_type":"video","start_time":"1.1","width":1280,"height":720,"codec_name":"h264",
        "avg_frame_rate":"30000/1001","duration":"N/A"},
        {"codec_type":"audio","start_time":"1.3","codec_name":"aac","sample_rate":"48000",
        "channels":2,"duration":"14.3"}]}''')
    info = parse_probe(data)
    assert info.video_duration == pytest.approx(14.9)
    assert info.audio_duration == 14.3
    assert info.audio_start - info.video_start == pytest.approx(0.2)
    assert info.fps == pytest.approx(29.97003)
    assert (info.width, info.height, info.sample_rate, info.channels) == (1280, 720, 48000, 2)
    assert parse_probe({}).audio_duration is None
    assert duration_warning(10, 9, 1) is None
    assert "before" in duration_warning(10, 7, -0.5)
    assert "after" in duration_warning(10, 12, 0.5)


def test_timing_validation_and_offset():
    tokens = tokenize("one two three four five")
    words = [Word(tokens[0], 0, 0.2), Word(tokens[1], 0.1, 0.3),
             Word(tokens[2], -0.2, 0.4), Word(tokens[3], 0.7, 1.001),
             Word(tokens[4], 0.6, 0.9)]
    checked = validate_words(words, 1)
    assert checked[1].issue == "Overlapping model intervals"
    assert checked[1].start == 0.1
    assert checked[2].start is None
    assert checked[3].end == 1
    assert checked[4].start is None
    assert validate_words([Word(tokens[0], 1, 1.0005)], 1)[0].start is None
    shown = presentation(checked, -0.2, 1)
    assert shown[0].issue == "Outside video after offset"
    assert shown[1].start == 0
    assert shown[1].end == pytest.approx(0.1)
    assert presentation(checked, 0.2, 1)[3].end == 1


def test_phrase_grouping_and_centiseconds():
    words = [Word(token, i / 2, i / 2 + 0.2)
             for i, token in enumerate(tokenize(" ".join(["unbroken"] * 80) + "\n\n आख़िरी।"))]
    groups = phrases(words, replace(Style(), words_per_line=3), 900)
    assert [w for group in groups for line in group for w in line] == words
    assert all(len(line) <= 3 for group in groups for line in group)
    assert groups[-1][0][0].token.paragraph
    assert ass_time(centiseconds(3599.996)) == "1:00:00.00"
    assert ass_time(centiseconds(3.456)) == "0:00:03.46"


def test_ass_keeps_text_and_highlights_intervals():
    tokens = tokenize("नमस्ते, दुनिया! {test} \\N")
    ass = generate_ass([Word(tokens[0], 0.101, 0.348), Word(tokens[1], 0.502, 0.89),
                        Word(tokens[2]), Word(tokens[3])], Style(), 1280, 720)
    assert "नमस्ते," in ass and "दुनिया!" in ass
    assert "0:00:00.10,0:00:00.35" in ass
    assert "0:00:00.35,0:00:00.50" in ass
    assert "0:00:00.50,0:00:00.89" in ass
    assert r"\1c&H57DBFF&" in ass and r"\1c&HD8C5B9&" in ass
    assert "\\\u200bN" in ass
    assert "Dialogue:" in generate_ass([Word(tokens[0], 0.1, 0.4)], Style(), 1280, 720)


def test_ctc_contract_with_repeated_letters_and_unaligned_tokens():
    tokens = tokenize("BeE! 123 a")
    alphabet = {"b": 1, "e": 2, "|": 3, "a": 4}
    expected = [0, 1, 2, 0, 2, 0, 3, 0, 4, 0]
    emissions = np.full((len(expected), 5), -12, dtype=np.float32)
    emissions[np.arange(len(expected)), expected] = -0.01
    words = align_emissions(emissions, alphabet, 0, tokens, 0.21, Cancellation())
    assert words[0].token.text == "BeE!"
    assert words[0].start == pytest.approx(0.0225)
    assert words[0].end == pytest.approx(0.1025)
    assert words[0].score > 0.98
    assert words[1].start is None and "alphabet" in words[1].issue
    assert words[2].start == pytest.approx(0.1625)
    with pytest.raises(EngineError, match="too short"):
        ctc_path(emissions[:2], [2, 2], 0, Cancellation())
    cancel = Cancellation()
    cancel.event.set()
    with pytest.raises(Cancelled):
        ctc_path(emissions, [1], 0, cancel)


def test_output_collisions(tmp_path):
    existing = tmp_path / "clip_karaoke.mp4"
    existing.write_bytes(b"original")
    first, second = tmp_path / "a", tmp_path / "b"
    first.write_bytes(b"video")
    second.write_bytes(b"report")
    outputs = publish(tmp_path, "clip", {".alignment.json": second, ".mp4": first})
    assert existing.read_bytes() == b"original"
    assert outputs[".mp4"].name == "clip_karaoke_2.mp4"
    assert not (tmp_path / "clip_karaoke.alignment.json").exists()
