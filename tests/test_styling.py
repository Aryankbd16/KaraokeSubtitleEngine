from dataclasses import replace

import pytest

from app.core import EngineError, Word, tokenize
from app.styles import StudioStyle, script_runs
from app.subtitles import generate_ass


def test_mixed_style_intervals_and_escaping():
    tokens = tokenize(r"प्रेमLove {शब्द} \N")
    words = [Word(tokens[0], .105, .32), Word(tokens[1], .5, .95), Word(tokens[2])]
    style = StudioStyle(hindi_font="Tiro Devanagari Hindi", hi_italic=True, en_weight=600,
                        hi_color="#112233", en_color="#654321", background=True,
                        shadow_color="#345678", shadow_opacity=80)
    ass = generate_ass(words, style, 720, 1280)
    assert r"\fnTiro Devanagari Hindi\b400\i1" in ass and r"\fnNoto Sans\b600\i0" in ass
    assert r"\1c&H332211&" in ass and r"\1c&H214365&" in ass
    assert r"\1c&H57DBFF&" in ass and r"\1c&HD8C5B9&" in ass
    assert r"\1a&H66&\p1" in ass and "&H33785634" in ass
    assert r"\{" in ass and "\\\u200bN" in ass
    assert "0:00:00.11,0:00:00.32" in ass and "0:00:00.32,0:00:00.50" in ass
    assert words[0].start == .105
    assert script_runs("“र्‍यो”Hello") == [(True, "“र्‍यो”"), (False, "Hello")]


def test_static_two_line_layout_and_validation():
    words = [Word(token, i, i + .5) for i, token in enumerate(tokenize("Hello नमस्ते"))]
    style = StudioStyle(karaoke=False, words_per_line=1, line_gap=25, vertical=6, horizontal=1,
                        outline_enabled=False, shadow_enabled=False, en_weight=400)
    ass = generate_ass(words, style, 1280, 720)
    events = [line for line in ass.splitlines() if line.startswith("Dialogue")]
    assert len(events) == 2 and all("0:00:00.00,0:00:01.50" in line for line in events)
    assert r"\an4" in events[0] and r"\b400\i0" in events[0]
    assert r"\pos(68.00,90.00)" in events[0] and r"\pos(68.00,167.00)" in events[1]
    with pytest.raises(EngineError):
        generate_ass(words, replace(style, width_percent=0), 1280, 720)

