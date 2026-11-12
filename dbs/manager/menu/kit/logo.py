from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

CURVE_STEPS = 10
SAMPLES_ACROSS = 4
SAMPLES_DOWN = 4
HALF = 0.5
VIEW_BOX = re.compile(r'viewBox="([^"]+)"')
PATH = re.compile(r'<path[^>]*\sd="([^"]+)"')
TOKEN = re.compile(r"[MmLlCcZzHhVv]|-?\d*\.?\d+(?:[eE][-+]?\d+)?")
ARITY = {"M": 2, "L": 2, "C": 6, "H": 1, "V": 1, "Z": 0}

Point = tuple[float, float]
Outline = list[list[Point]]


@dataclass(frozen=True)
class Logo:
    left: float
    top: float
    width: float
    height: float
    shapes: tuple

    def rows_for(self, columns: int) -> int:
        halves = columns * self.height / self.width
        return max(int(halves / 2 + HALF), 1)


def outlines(svg: str) -> Logo:
    left, top, width, height = (
        float(part) for part in VIEW_BOX.search(svg).group(1).split()
    )
    shapes = tuple(
        tuple(tuple(ring) for ring in _shape(data)) for data in PATH.findall(svg)
    )
    return Logo(left, top, width, height, shapes)


@lru_cache(maxsize=8)
def coverage(logo: Logo, columns: int, rows: int) -> tuple:
    across = columns * SAMPLES_ACROSS
    down = rows * 2 * SAMPLES_DOWN
    filled = [[0] * columns for _ in range(rows * 2)]
    for line in range(down):
        y = logo.top + (line + HALF) * logo.height / down
        spans = [span for shape in logo.shapes for span in _spans(shape, y)]
        if not spans:
            continue
        for sample in range(across):
            x = logo.left + (sample + HALF) * logo.width / across
            if any(start <= x < end for start, end in spans):
                filled[line // SAMPLES_DOWN][sample // SAMPLES_ACROSS] += 1
    full = SAMPLES_ACROSS * SAMPLES_DOWN
    return tuple(
        tuple(
            (filled[2 * row][column] / full, filled[2 * row + 1][column] / full)
            for column in range(columns)
        )
        for row in range(rows)
    )


def blocks(logo: Logo, columns: int, rows: int) -> list[str]:
    return [
        "".join(_block(top, bottom) for top, bottom in row).rstrip()
        for row in coverage(logo, columns, rows)
    ]


def _block(top: float, bottom: float) -> str:
    upper, lower = top >= HALF, bottom >= HALF
    if upper and lower:
        return "█"
    if upper:
        return "▀"
    return "▄" if lower else " "


def _spans(shape: tuple, y: float) -> list[tuple[float, float]]:
    crossings = []
    for ring in shape:
        for (x1, y1), (x2, y2) in zip(ring, (*ring[1:], ring[0])):
            if (y1 <= y < y2) or (y2 <= y < y1):
                x = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
                crossings.append((x, 1 if y2 > y1 else -1))
    crossings.sort()
    spans = []
    winding = 0
    for index, (x, turn) in enumerate(crossings):
        before = winding
        winding += turn
        if before == 0 and winding != 0:
            start = x
        elif before != 0 and winding == 0:
            spans.append((start, x))
    return spans


def _shape(data: str) -> Outline:
    rings: Outline = []
    ring: list[Point] = []
    position = (0.0, 0.0)
    for command, numbers in _commands(data):
        relative = command.islower()
        kind = command.upper()
        if kind == "Z":
            if ring:
                rings.append(ring)
                position = ring[0]
            ring = []
            continue
        if kind == "M":
            if ring:
                rings.append(ring)
            position = _moved(position, numbers, relative)
            ring = [position]
        elif kind == "L":
            position = _moved(position, numbers, relative)
            ring.append(position)
        elif kind == "H":
            position = (numbers[0] + (position[0] if relative else 0.0), position[1])
            ring.append(position)
        elif kind == "V":
            position = (position[0], numbers[0] + (position[1] if relative else 0.0))
            ring.append(position)
        elif kind == "C":
            points = [
                _moved(position, numbers[index : index + 2], relative)
                for index in (0, 2, 4)
            ]
            ring.extend(_curve(position, *points))
            position = points[2]
    if ring:
        rings.append(ring)
    return rings


def _commands(data: str):
    tokens = TOKEN.findall(data)
    index = 0
    command = ""
    while index < len(tokens):
        if tokens[index].isalpha():
            command = tokens[index]
            index += 1
            if command.upper() == "Z":
                yield command, []
                continue
        arity = ARITY[command.upper()]
        numbers = [float(value) for value in tokens[index : index + arity]]
        index += arity
        yield command, numbers
        if command == "M":
            command = "L"
        elif command == "m":
            command = "l"


def _moved(position: Point, numbers: list, relative: bool) -> Point:
    if relative:
        return (position[0] + numbers[0], position[1] + numbers[1])
    return (numbers[0], numbers[1])


def _curve(start: Point, first: Point, second: Point, end: Point) -> list[Point]:
    points = []
    for step in range(1, CURVE_STEPS + 1):
        t = step / CURVE_STEPS
        s = 1 - t
        points.append(
            (
                s**3 * start[0]
                + 3 * s * s * t * first[0]
                + 3 * s * t * t * second[0]
                + t**3 * end[0],
                s**3 * start[1]
                + 3 * s * s * t * first[1]
                + 3 * s * t * t * second[1]
                + t**3 * end[1],
            )
        )
    return points
