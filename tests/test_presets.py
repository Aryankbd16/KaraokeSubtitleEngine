from dataclasses import asdict, replace
import json

import pytest

from app.core import EngineError
from app.presets import BUILTINS, DEFAULT, PresetStore, decode_style
from app.subtitles import generate_ass
from app.core import Word, tokenize


def test_all_builtins_and_custom_lifecycle(tmp_path):
    store = PresetStore(tmp_path / "styles.json")
    for style in BUILTINS.values():
        assert "Dialogue:" in generate_ass([Word(tokenize("नमस्ते")[0], 0, 1)], style, 640, 360)
    style = replace(BUILTINS[DEFAULT], en_italic=True)
    store.change("apply", DEFAULT, style=style)
    assert not BUILTINS[DEFAULT].en_italic
    store.change("create", "गीत", style=style)
    store.change("rename", "गीत", new_name="Poem")
    again = PresetStore(store.path)
    assert again.selected == "Poem" and again.current == again.custom["Poem"] == style
    again.change("update", "Poem", style=BUILTINS["Clean Reel"])
    store.change("delete", "Poem")
    assert not store.custom and store.current == BUILTINS[DEFAULT]
    with pytest.raises(EngineError):
        store.change("delete", DEFAULT)
    with pytest.raises(EngineError):
        store.change("create", DEFAULT.lower(), style=style)


@pytest.mark.parametrize("data", ["{", "null", '{"version": 99}', '{"version": 0}'])
def test_unknown_library_preserved(tmp_path, data):
    path = tmp_path / "styles.json"
    path.write_text(data)
    store = PresetStore(path)
    assert store.notice and store.current == BUILTINS[DEFAULT]
    with pytest.raises(EngineError):
        store.change("apply", DEFAULT, style=store.current)
    assert path.read_text() == data


def test_invalid_entry_isolated_and_supported_weights_restored(tmp_path):
    style = asdict(BUILTINS["Poetry / Shayari"])
    style.update(hi_weight=700, hi_italic=True)
    assert decode_style(style).hi_weight == 400
    path = tmp_path / "styles.json"
    path.write_text(json.dumps({"version": 1, "presets": {"Bad": {"size": True}, "Good": style}}))
    store = PresetStore(path)
    assert set(store.custom) == {"Good"} and store.notice

