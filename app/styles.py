"""Presentation-only configuration and shaping metrics in ASS script units."""
from dataclasses import dataclass
from functools import lru_cache
import re
import struct
import unicodedata

import uharfbuzz as hb

from .core import EngineError, Style
from .font_library import ENGLISH, HINDI, Face, resolve


@dataclass(frozen=True)
class StudioStyle(Style):
    font: str = "Noto Sans"
    hindi_font: str = "Noto Sans Devanagari"
    en_weight: int = 700
    hi_weight: int = 700
    en_italic: bool = False
    hi_italic: bool = False
    en_color: str | None = None
    hi_color: str | None = None
    karaoke: bool = True
    color_completed: bool = True
    outline_enabled: bool = True
    shadow_enabled: bool = True
    shadow_color: str = "#000000"
    shadow_opacity: int = 50
    background: bool = False
    box_color: str = "#10141D"
    box_opacity: int = 60
    line_gap: int = 4
    width_percent: int = 90

    def validate(self) -> None:
        super().validate()
        if self.font not in ENGLISH or self.hindi_font not in HINDI:
            raise EngineError("Choose a bundled family for each script.")
        if not (0 <= self.line_gap <= 100 and 20 <= self.width_percent <= 100
                and 0 <= self.box_opacity <= 100 and 0 <= self.shadow_opacity <= 100):
            raise EngineError("Layout or opacity is outside its supported range.")
        for color in (self.en_color, self.hi_color, self.shadow_color, self.box_color):
            if color is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                raise EngineError("Choose valid subtitle colors.")
        for face in self.faces:
            face.path()
            shaped_font(face)

    @property
    def faces(self) -> tuple[Face, Face]:
        return (resolve(self.font, self.en_weight, self.en_italic),
                resolve(self.hindi_font, self.hi_weight, self.hi_italic))


def script_runs(text: str, default_hindi: bool = False):
    """Keep joiners, combining marks and trailing punctuation with their base."""
    runs = []
    start = 0
    script = None
    for i, char in enumerate(text):
        if "\u0900" <= char <= "\u097f" or "\ua8e0" <= char <= "\ua8ff":
            hindi = True
        elif unicodedata.category(char)[0] in "LN":
            hindi = False
        else:
            continue
        if script is not None and hindi != script:
            runs.append((script, text[start:i]))
            start = i
        script = hindi
    runs.append((default_hindi if script is None else script, text[start:]))
    return runs


@lru_cache(maxsize=32)
def shaped_font(face: Face) -> hb.Font:
    data = hb.Face(face.path().read_bytes())
    family = data.get_name(16) or data.get_name(1)
    metadata = data.reference_table("OS/2").data
    if (family != face.family or len(metadata) < 78 or data.glyph_count < 2
            or struct.unpack_from(">H", metadata, 4)[0] != face.weight
            or bool(struct.unpack_from(">H", metadata, 62)[0] & 1) != face.italic):
        raise EngineError(f"Invalid bundled face {face.filename}. Restore the original font file.")
    return hb.Font(data)


@lru_cache(maxsize=32)
def ass_font_height(face: Face) -> int:
    # libass set_font_metrics uses OS/2 usWinAscent + usWinDescent for these static TTFs.
    table = shaped_font(face).face.reference_table("OS/2").data
    return sum(struct.unpack_from(">HH", table, 74))


@lru_cache(maxsize=8192)
def advance(face: Face, text: str) -> float:
    font = shaped_font(face)
    buffer = hb.Buffer()
    buffer.add_str(text)
    buffer.guess_segment_properties()
    hb.shape(font, buffer)
    if any(glyph.codepoint == 0 for glyph in buffer.glyph_infos):
        raise EngineError(f"{face.family} has no glyph for part of “{text}”. Choose another family or edit the display text.")
    # libass scales FreeType's real font height to ASS fontsize.
    return sum(p.x_advance for p in buffer.glyph_positions) / ass_font_height(face)
