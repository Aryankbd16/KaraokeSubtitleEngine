from __future__ import annotations

import math
import re
import threading
import unicodedata as ud
from dataclasses import dataclass, replace
from pathlib import Path


class EngineError(Exception):
    """An actionable processing error."""


class Cancelled(EngineError):
    pass


class Cancellation:
    def __init__(self) -> None:
        self.event = threading.Event()

    def check(self) -> None:
        if self.event.is_set():
            raise Cancelled("Processing cancelled.")


VIDEO = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
AUDIO = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}


def validate_file(path: Path, extensions: set[str]) -> None:
    if path.suffix.lower() not in extensions:
        raise EngineError(f"Select a supported file ({', '.join(sorted(extensions))}).")
    try:
        with path.open("rb") as source:
            if not source.read(1):
                raise EngineError(f"{path.name} is empty.")
    except OSError as exc:
        raise EngineError(f"Cannot read {path.name}.") from exc


@dataclass(frozen=True)
class Token:
    text: str
    normalized: str
    paragraph: bool = False


def tokenize(script: str) -> list[Token]:
    tokens: list[Token] = []
    for block in re.split(r"\n\s*\n", script.replace("\r\n", "\n")):
        for index, word in enumerate(block.split()):
            normalized = "".join(
                c for c in ud.normalize("NFKC", word).casefold()
                if ud.category(c)[0] in "LMN" or c in "'’"
            ).replace("’", "'").strip("'")
            tokens.append(Token(word, normalized, index == 0 and bool(tokens)))
    if not any(token.normalized for token in tokens):
        raise EngineError("Enter a script containing words.")
    return tokens


@dataclass(frozen=True)
class Word:
    token: Token
    start: float | None = None
    end: float | None = None
    score: float | None = None
    issue: str | None = None


def validate_words(words: list[Word], duration: float) -> list[Word]:
    result: list[Word] = []
    last_start = -1.0
    last_end = -1.0
    for word in words:
        start, end = word.start, word.end
        if start is None or end is None:
            result.append(replace(word, start=None, end=None, issue=word.issue or "Unaligned"))
        elif not (math.isfinite(start) and math.isfinite(end)
                  and 0 <= start < duration and start < end <= duration + 0.001
                  and start >= last_start):
            result.append(replace(word, start=None, end=None, issue="Invalid model timing"))
        else:
            issue = word.issue or ("Overlapping model intervals" if start < last_end else None)
            result.append(replace(word, end=min(duration, end), issue=issue))
            last_start, last_end = start, max(last_end, end)
    return result


def presentation(words: list[Word], offset: float, duration: float) -> list[Word]:
    result = []
    for word in words:
        if word.start is None or word.end is None:
            result.append(word)
            continue
        start, end = max(0.0, word.start + offset), min(duration, word.end + offset)
        if start < end:
            result.append(replace(word, start=start, end=end))
        else:
            result.append(replace(word, start=None, end=None, issue="Outside video after offset"))
    return result


@dataclass(frozen=True)
class Style:
    font: str = "Segoe UI"
    size: int = 48
    normal: str = "#FFFFFF"
    active: str = "#FFDB57"
    completed: str = "#B9C5D8"
    outline: str = "#141923"
    stroke: float = 3
    shadow: float = 1
    horizontal: int = 2
    vertical: int = 0
    words_per_line: int = 7
    margin: int = 64

    def validate(self) -> None:
        if not self.font.strip() or any(c in self.font for c in ",\r\n"):
            raise EngineError("Select a valid subtitle font.")
        if not (16 <= self.size <= 120 and 0 <= self.stroke <= 10 and 0 <= self.shadow <= 10
                and self.horizontal in (1, 2, 3) and self.vertical in (0, 3, 6)
                and 1 <= self.words_per_line <= 20 and 0 <= self.margin <= 200):
            raise EngineError("Subtitle style is outside the supported range.")
        if any(not re.fullmatch(r"#[0-9a-fA-F]{6}", c)
               for c in (self.normal, self.active, self.completed, self.outline)):
            raise EngineError("Select valid subtitle colors.")


@dataclass(frozen=True)
class Project:
    video: Path
    audio: Path | None
    script: str
    language: str
    output_dir: Path
    style: Style = Style()
    offset: float = 0
    crf: int = 20
    export_ass: bool = False
    device: str = "cpu"

    def validate(self) -> list[Token]:
        validate_file(self.video, VIDEO)
        if self.audio:
            validate_file(self.audio, AUDIO)
        if not self.output_dir.is_dir():
            raise EngineError("Choose an existing output folder.")
        if not math.isfinite(self.offset) or abs(self.offset) > 120 or (self.offset and not self.audio):
            raise EngineError("An offset between −120 and +120 seconds requires replacement audio.")
        if not 15 <= self.crf <= 29 or self.device not in {"cpu", "auto"}:
            raise EngineError("Invalid encoding quality or device.")
        self.style.validate()
        return tokenize(self.script)
