"""Built-in studio looks and the versioned local preset library."""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import MappingProxyType

from PySide6.QtCore import QLockFile

from .core import EngineError
from .styles import StudioStyle

DEFAULT = "Karaoke Highlight"
BUILTINS = MappingProxyType({
    "Clean Reel": StudioStyle(karaoke=False, size=68, stroke=4, shadow=2, words_per_line=5),
    "Mixed Typography": StudioStyle(karaoke=False, hindi_font="Mukta", hi_weight=600,
                                    en_weight=500, en_italic=True, hi_color="#FFF2D1",
                                    en_color="#91CFFF", size=64, line_gap=12),
    DEFAULT: StudioStyle(),
    "Poetry / Shayari": StudioStyle(karaoke=False, hindi_font="Tiro Devanagari Hindi",
                                    en_weight=400, hi_weight=400, en_italic=True, size=60,
                                    normal="#FBE7C4", stroke=1, shadow=3, line_gap=18, margin=92),
})
SCHEMA = 1


def decode_style(data: dict) -> StudioStyle:
    defaults = asdict(StudioStyle())
    if not isinstance(data, dict) or data.keys() - defaults.keys():
        raise ValueError("Unknown style settings")
    for key, value in data.items():
        default = defaults[key]
        if default is None:
            valid = value is None or isinstance(value, str)
        elif key in ("stroke", "shadow"):
            valid = type(value) in (int, float)
        else:
            valid = type(value) is type(default)
        if not valid:
            raise ValueError(f"Invalid {key}")
    style = StudioStyle(**data)
    style.validate()
    en, hi = style.faces
    return replace(style, en_weight=en.weight, hi_weight=hi.weight, en_italic=en.italic, hi_italic=hi.italic)


def valid_name(name: str) -> bool:
    return (isinstance(name, str) and 0 < len(name.strip()) <= 64 and name.strip() == name
            and name.isprintable() and name.casefold() not in {key.casefold() for key in BUILTINS})


class PresetStore:
    def __init__(self, path: Path):
        self.path = path
        self.reload()

    def reload(self):
        self.custom = {}
        self.selected = DEFAULT
        self.current = BUILTINS[DEFAULT]
        self.notice = ""
        self.read_only = False
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != SCHEMA:
                raise ValueError("Unsupported schema")
            if not isinstance(data.get("presets"), dict):
                raise ValueError("Invalid preset library")
            for name, value in data["presets"].items():
                if valid_name(name):
                    try:
                        self.custom[name] = decode_style(value)
                    except (EngineError, ValueError, TypeError):
                        self.notice = "Some invalid saved presets were skipped."
            selected = data.get("selected")
            if isinstance(selected, str) and (selected in BUILTINS or selected in self.custom):
                self.selected = selected
            default_style = (BUILTINS | self.custom)[self.selected]
            try:
                self.current = decode_style(data.get("current", asdict(default_style)))
            except (TypeError, ValueError, EngineError):
                self.current = default_style
                self.notice = "The saved style was invalid. The selected preset was restored."
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, EngineError, RecursionError):
            self.notice = f"Using default styling. The unreadable or incompatible file was preserved at {self.path}."
            self.read_only = True

    def change(self, operation, name, *, style=None, new_name=None):
        """Serialize read-modify-replace across app instances and preserve the previous file on failure."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lock = QLockFile(str(self.path) + ".lock")
            if not lock.tryLock(1000):
                raise EngineError("Another window is saving presets. Try again.")
            try:
                self.reload()
                if self.read_only:
                    raise EngineError(self.notice)
                custom = dict(self.custom)
                selected, current = self.selected, self.current
                if operation in ("create", "rename"):
                    target = new_name if operation == "rename" else name
                    if not valid_name(target) or any(n.casefold() == target.casefold() for n in custom
                                                     if operation == "create" or n != name):
                        raise EngineError("Choose a unique custom name of 1 to 64 characters.")
                if operation in ("update", "rename", "delete") and name not in custom:
                    raise EngineError("Only an existing custom preset can be changed.")
                if operation in ("create", "update", "apply"):
                    snapshot = decode_style(asdict(style))
                    if operation == "apply":
                        selected, current = name, snapshot
                    else:
                        custom[name] = snapshot
                    if name not in custom and name not in BUILTINS:
                        raise EngineError("The selected preset no longer exists.")
                elif operation == "rename":
                    custom[new_name] = custom.pop(name)
                    selected = new_name if selected == name else selected
                elif operation == "delete":
                    del custom[name]
                    if selected == name:
                        selected, current = DEFAULT, BUILTINS[DEFAULT]
                else:
                    raise ValueError("Unknown preset operation")
                data = {"version": SCHEMA, "selected": selected, "current": asdict(current),
                        "presets": {n: asdict(s) for n, s in custom.items()}}
                with NamedTemporaryFile(dir=self.path.parent, delete=False) as temp:
                    pending = Path(temp.name)
                try:
                    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                    os.replace(pending, self.path)
                finally:
                    pending.unlink(missing_ok=True)
                self.custom, self.selected, self.current = custom, selected, current
            finally:
                lock.unlock()
        except OSError as exc:
            raise EngineError(f"Could not save presets in {self.path.parent}.") from exc
