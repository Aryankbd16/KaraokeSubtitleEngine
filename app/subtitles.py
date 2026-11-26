from __future__ import annotations

import math
import unicodedata

from .core import Style, Word

STOPS = (".", "!", "?", "।", "॥", "…")


def text_width(text: str) -> float:
    return sum(0 if unicodedata.category(c).startswith("M") else
               1 if unicodedata.east_asian_width(c) in {"W", "F"} else 0.62
               for c in text)


def phrases(words: list[Word], style: Style, width: int) -> list[list[list[Word]]]:
    budget = max(6, (width - 2 * style.margin) / style.size)
    groups: list[list[list[Word]]] = []
    lines: list[list[Word]] = [[]]
    previous: Word | None = None
    for word in words:
        line = lines[-1]
        pause = (previous is not None and previous.end is not None and word.start is not None
                 and word.start - previous.end > 0.65)
        boundary = (previous is not None and previous.token.text.endswith(STOPS)
                    and word.start is not None)
        if line and (word.token.paragraph or pause or (boundary and len(line) > 1)):
            groups.append(lines)
            lines = [[]]
            line = lines[-1]
        candidate = " ".join(item.token.text for item in [*line, word])
        if line and (len(line) >= style.words_per_line or text_width(candidate) > budget):
            if len(lines) == 2:
                groups.append(lines)
                lines = [[]]
            else:
                lines.append([])
            line = lines[-1]
        line.append(word)
        previous = word
    if lines[0]:
        groups.append(lines)
    return groups


def centiseconds(seconds: float) -> int:
    return max(0, math.floor(seconds * 100 + 0.5))


def ass_time(cs: int) -> str:
    hours, rest = divmod(cs, 360000)
    minutes, rest = divmod(rest, 6000)
    seconds, fraction = divmod(rest, 100)
    return f"{hours}:{minutes:02}:{seconds:02}.{fraction:02}"


def ass_color(value: str) -> str:
    return f"&H{value[5:7]}{value[3:5]}{value[1:3]}&"


def escape_text(text: str) -> str:
    # libass handles escaped braces. Break literal backslash sequences such as \N.
    return "".join(c + "\u200b" if c == "\\" else
                   "\\" + c if c in "{}" else c for c in text)


def generate_ass(words: list[Word], style: Style, display_width: int,
                 display_height: int) -> str:
    height = 1080
    width = max(2, round(height * display_width / display_height))
    primary = ass_color(style.normal)
    outline = ass_color(style.outline)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,{style.font},{style.size},{primary},{primary},{outline},&H80000000,-1,0,0,0,100,100,0,0,1,{style.stroke},{style.shadow},{style.horizontal + style.vertical},{style.margin},{style.margin},{style.margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    for layer, group in enumerate(phrases(words, style, width)):
        intervals = {id(word): (centiseconds(word.start), centiseconds(word.end))
                     for line in group for word in line
                     if word.start is not None and word.end is not None}
        bounds = sorted({point for start, end in intervals.values() if start < end
                         for point in (start, end)})
        for start, end in zip(bounds, bounds[1:]):
            rows = []
            for line in group:
                pieces = []
                for word in line:
                    interval = intervals.get(id(word))
                    color = style.normal
                    if interval and interval[0] < interval[1]:
                        if interval[0] <= start < interval[1]:
                            color = style.active
                        elif interval[1] <= start:
                            color = style.completed
                    pieces.append(r"{\1c" + ass_color(color) + "}" + escape_text(word.token.text))
                rows.append(" ".join(pieces))
            text = r"\N".join(rows)
            events.append(f"Dialogue: {layer},{ass_time(start)},{ass_time(end)},Karaoke,,0,0,0,,{text}")
    return header + "\n".join(events) + "\n"
