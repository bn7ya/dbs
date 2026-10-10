from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Union

from rest_framework.exceptions import APIException

Column = tuple[str, Union[str, Callable[[Mapping[str, Any]], Any]]]

EMPTY = "-"


class Output:
    def __init__(self, as_json: bool = False) -> None:
        self.as_json = as_json

    def json(self, data: Any) -> None:
        print(json.dumps(data, indent=2, default=str, ensure_ascii=False))

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
            print(empty)
            return
        cells = [[text(value_of(row, key)) for _, key in columns] for row in rows]
        headers = [header for header, _ in columns]
        widths = [
            max(len(header), *(len(line[index]) for line in cells))
            for index, header in enumerate(headers)
        ]
        print(_line(headers, widths))
        for line in cells:
            print(_line(line, widths))

    def fields(self, data: Mapping[str, Any], names: Iterable[str]) -> None:
        if self.as_json:
            self.json(data)
            return
        shown = [name for name in names if name in data]
        width = max((len(label(name)) for name in shown), default=0)
        for name in shown:
            print(f"{label(name):<{width}}  {text(data[name])}")

    def say(self, message: str, data: Any = None) -> None:
        if self.as_json:
            self.json({"message": message} if data is None else data)
        else:
            print(message)


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


def problem(exc: APIException) -> str:
    return _flatten(exc.detail)


def _flatten(detail: Any, field: str = "") -> str:
    if isinstance(detail, dict):
        return "; ".join(
            _flatten(value, key if key != "non_field_errors" else "")
            for key, value in detail.items()
        )
    if isinstance(detail, list):
        return "; ".join(_flatten(item, field) for item in detail)
    message = str(detail)
    return f"{label(field)}: {message}" if field else message


def _line(cells: Sequence[str], widths: Sequence[int]) -> str:
    return "  ".join(cell.ljust(width) for cell, width in zip(cells, widths)).rstrip()
