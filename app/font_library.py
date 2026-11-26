"""Static, unmodified OFL faces shared by Qt and libass."""
from dataclasses import dataclass
from pathlib import Path
import os
import shutil

from .core import EngineError

FONT_DIR = Path(__file__).with_name("fonts")
WEIGHTS = {400: "Regular", 500: "Medium", 600: "SemiBold", 700: "Bold"}
HINDI = ("Noto Sans Devanagari", "Noto Serif Devanagari", "Mukta", "Hind", "Tiro Devanagari Hindi")
ENGLISH = ("Noto Sans", "Mukta", "Hind", "Tiro Devanagari Hindi")
FAMILIES = tuple(dict.fromkeys((*ENGLISH, *HINDI)))


def weights(family: str) -> tuple[int, ...]:
    if family not in FAMILIES:
        raise EngineError(f"Unknown bundled font: {family}")
    return (400,) if family == "Tiro Devanagari Hindi" else tuple(WEIGHTS)


def has_italic(family: str) -> bool:
    return family in ("Tiro Devanagari Hindi", "Noto Sans")


@dataclass(frozen=True)
class Face:
    family: str
    weight: int
    italic: bool

    @property
    def filename(self) -> str:
        style = WEIGHTS[self.weight]
        if self.italic:
            style = "Italic" if self.weight == 400 else style + "Italic"
        return f"{self.family.replace(' ', '')}-{style}.ttf"

    def path(self, root: Path = FONT_DIR) -> Path:
        source = root / self.family.replace(" ", "") / self.filename
        if not source.is_file():
            raise EngineError(f"Missing bundled font {self.filename}. Restore the app/fonts directory.")
        return source


def resolve(family: str, weight: int, italic: bool) -> Face:
    nearest = min(weights(family), key=lambda candidate: abs(candidate - weight))
    return Face(family, nearest, italic and has_italic(family))


def all_faces():
    for family in FAMILIES:
        for weight in weights(family):
            yield Face(family, weight, False)
            if has_italic(family):
                yield Face(family, weight, True)


def stage_fonts(work: Path, faces=None) -> None:
    """Use a flat, ASCII relative fontsdir so filtergraph escaping is independent of user paths."""
    directory = work / "fonts"
    directory.mkdir(exist_ok=True)
    for face in all_faces() if faces is None else set(faces):
        source = face.path()
        target = directory / face.filename
        if target.exists():
            continue
        try:
            os.link(source, target)
        except OSError:
            shutil.copyfile(source, target)

