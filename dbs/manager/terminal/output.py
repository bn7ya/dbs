from __future__ import annotations

import json
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, TextIO, Union

Column = tuple[str, Union[str, Callable[[Mapping[str, Any]], Any]]]

EMPTY = "-"


class Output:
    def __init__(self, as_json: bool = False, stream: TextIO | None = None) -> None:
        self.as_json = as_json
        self.stream = stream

    def line(self, message: str = "", *, end: str = "\n") -> None:
        print(message, end=end, file=self.stream or sys.stdout, flush=True)

    def json(self, data: Any) -> None:
        self.line(json.dumps(data, indent=2, default=str, ensure_ascii=False))

    def table(
        self,
        rows: Sequence[Mapping[str, Any]],
        columns: Sequence[Column],
        *,
        empty: str,
        data: Any = None,
    ) -> None:
        if self.as_json:
            self.json(rows if data is None else data)
            return
        if not rows:
            self.line(empty)
            return
        cells = [[text(value_of(row, key)) for _, key in columns] for row in rows]
        headers = [header for header, _ in columns]
        widths = [
            max(len(header), *(len(line[index]) for line in cells))
            for index, header in enumerate(headers)
        ]
        self.line(_line(headers, widths))
        for cell_line in cells:
            self.line(_line(cell_line, widths))

    def fields(self, data: Mapping[str, Any], names: Iterable[str]) -> None:
        if self.as_json:
            self.json(data)
            return
        shown = [name for name in names if name in data]
        width = max((len(label(name)) for name in shown), default=0)
        for name in shown:
            self.line(f"{label(name):<{width}}  {text(data[name])}")

    def say(self, message: str, data: Any = None) -> None:
        if self.as_json:
            self.json({"message": message} if data is None else data)
        else:
            self.line(message)


def value_of(row: Mapping[str, Any], key: Any) -> Any:
    return key(row) if callable(key) else row.get(key)


def text(value: Any) -> str:
    if value is None or value == "" or value == []:
        return EMPTY
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):
        return ", ".join(text(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, default=str, ensure_ascii=False)
    return str(value)


def label(name: str) -> str:
    return name.replace("_", " ")


def _line(cells: Sequence[str], widths: Sequence[int]) -> str:
    return "  ".join(cell.ljust(width) for cell, width in zip(cells, widths)).rstrip()
