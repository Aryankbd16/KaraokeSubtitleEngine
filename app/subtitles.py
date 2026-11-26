from __future__ import annotations

import math
import unicodedata

from .core import Style, Word
from .styles import StudioStyle, advance, script_runs

STOPS = (".", "!", "?", "।", "॥", "…")


def text_width(text: str) -> float:
    return sum(0 if unicodedata.category(c).startswith("M") else
               1 if unicodedata.east_asian_width(c) in {"W", "F"} else 0.62
               for c in text)


def phrases(words: list[Word], style: Style, width: int) -> list[list[list[Word]]]:
    budget = max(6, (width - 2 * style.margin) / style.size)
    measure = text_width
    if isinstance(style, StudioStyle):
        faces = style.faces
        budget = available_width(style, width) / style.size

        def measure(text):
            return sum(advance(faces[hindi], run) for hindi, run in script_runs(text))
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
    style.validate()
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
    if isinstance(style, StudioStyle):
        return studio_ass(header, words, style, width, height)
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

def available_width(style: StudioStyle, width: int) -> float:
    return max(1, min(width - 2 * min(style.margin, width // 4), width * style.width_percent / 100)
               - 2 * (style.stroke + style.shadow + 4))


def alpha(opacity: int) -> str:
    return f"&H{round(255 * (1 - opacity / 100)):02X}&"


def studio_ass(header: str, words: list[Word], style: StudioStyle, width: int, height: int) -> str:
    faces = style.faces
    stroke = style.stroke if style.outline_enabled else 0
    shadow = style.shadow if style.shadow_enabled else 0
    # The base style also describes the caption when inspected in an ASS editor.
    fields = [style.font, style.size, ass_color(style.normal), ass_color(style.active),
              ass_color(style.outline), "&H" + alpha(style.shadow_opacity)[2:4] +
              ass_color(style.shadow_color)[2:-1], -1 if faces[0].weight >= 700 else 0,
              -1 if faces[0].italic else 0, 0, 0, 100, 100, 0, 0, 1, stroke, shadow,
              style.horizontal + style.vertical, style.margin, style.margin, style.margin, 1]
    base = "Style: Karaoke," + ",".join(str(value).rstrip("&") for value in fields)
    header = "\n".join(base if line.startswith("Style: Karaoke,") else line for line in header.splitlines())
    events = [header]
    limit = available_width(style, width)
    inset = min(style.margin, width // 4) + stroke + shadow + 4
    x = (inset, width / 2, width - inset)[style.horizontal - 1]
    line_height = style.size + 2 * stroke + shadow + 4

    for index, group in enumerate(phrases(words, style, width)):
        intervals = {word: (centiseconds(word.start), centiseconds(word.end))
                     for line in group for word in line if word.start is not None and word.end is not None}
        bounds = sorted({point for a, b in intervals.values() if a < b for point in (a, b)})
        if len(bounds) < 2:
            continue
        top = style.margin
        block_height = len(group) * line_height + (len(group) - 1) * style.line_gap
        if style.vertical == 0:
            top = height - style.margin - block_height
        elif style.vertical == 3:
            top = (height - block_height) / 2

        def event(layer, a, b, text):
            events.append(f"Dialogue: {index * 2 + layer},{ass_time(a)},{ass_time(b)},Karaoke,,0,0,0,,{text}")

        for row_index, line in enumerate(group):
            y = top + row_index * (line_height + style.line_gap)
            runs = []
            length = 0
            previous_hindi = False
            for word_index, word in enumerate(line):
                word_runs = script_runs(word.token.text, previous_hindi)
                for run_index, (hindi, run) in enumerate(word_runs):
                    face = faces[hindi]
                    parts = run + (" " if word_index < len(line) - 1 and
                                   run_index == len(word_runs) - 1 else "")
                    length += advance(face, parts) * style.size
                    tags = rf"\fn{face.family}\b{face.weight}\i{int(face.italic)}"
                    color = (style.hi_color if hindi else style.en_color) or style.normal
                    runs.append((word, tags, color, escape_text(parts)))
                    previous_hindi = hindi
            scale = min(1, limit / max(1, length))
            pos = rf"{{\an{3 + style.horizontal}\pos({x:.2f},{y + line_height / 2:.2f})\fscx{scale*100:.2f}}}"
            if style.background:
                box_width = min(limit, length) + 2 * (stroke + 4)
                left = x - (style.horizontal - 1) * min(limit, length) / 2 - stroke - 4
                drawing = (rf"{{\an7\pos({left:.2f},{y:.2f})\bord0\shad0\1c{ass_color(style.box_color)}"
                           rf"\1a{alpha(style.box_opacity)}\p1}}m 0 0 l {round(box_width)} 0 "
                           f"{round(box_width)} {round(line_height)} 0 {round(line_height)}")
                event(0, bounds[0], bounds[-1], drawing)
            points = bounds if style.karaoke else [bounds[0], bounds[-1]]
            for start, end in zip(points, points[1:]):
                pieces = [pos]
                for word, tags, base_color, display in runs:
                    color = base_color
                    interval = intervals.get(word)
                    if style.karaoke and interval and interval[0] < interval[1]:
                        if interval[0] <= start < interval[1]:
                            color = style.active
                        elif style.color_completed and interval[1] <= start:
                            color = style.completed
                    pieces.append(rf"{{{tags}\1c{ass_color(color)}}}{display}")
                event(1, start, end, "".join(pieces))
    return "\n".join(events) + "\n"

