from __future__ import annotations

import argparse
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

VALUE = "value"
SWITCH = "switch"
MANY = "many"
PLACEHOLDER = "\x00held-{index}"


class Refused(Exception):
    pass


class FormParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise Refused(message)

    def exit(self, status: int = 0, message: Any = None) -> None:
        raise Refused((message or "").strip())


@dataclass(frozen=True)
class Argument:
    key: str
    dest: str
    flag: str
    kind: str
    help: str
    choices: tuple
    required: bool
    default: Any
    group: Any
    number: bool

    @property
    def positional(self) -> bool:
        return not self.flag

    @property
    def label(self) -> str:
        words = (self.flag.lstrip("-") if self.flag else self.dest).replace("_", "-")
        return words.replace("-", " ").capitalize()


@dataclass(frozen=True)
class Verb:
    path: tuple
    help: str
    handler: Any
    arguments: tuple

    @property
    def inside(self) -> bool:
        return isinstance(self.handler, str)

    @property
    def name(self) -> str:
        return " ".join(self.path)

    def argument(self, key: str) -> Argument:
        for argument in self.arguments:
            if argument.key == key:
                return argument
        raise KeyError(key)


@lru_cache(maxsize=1)
def parser() -> argparse.ArgumentParser:
    from dbs.manager.cli import build_parser

    return build_parser(parser_class=FormParser)


@lru_cache(maxsize=1)
def catalogue() -> tuple:
    return tuple(verbs(parser()))


def verb(*path: str) -> Verb:
    for found in catalogue():
        if found.path == path:
            return found
    raise KeyError(path)


def verbs(root: argparse.ArgumentParser) -> list[Verb]:
    found: list[Verb] = []
    _walk(root, (), "", found)
    return found


def words(item: Verb, values: Mapping[str, Any]) -> list[str]:
    options: list[str] = []
    positionals: list[str] = []
    for argument in item.arguments:
        value = values.get(argument.key)
        if absent(value):
            continue
        if argument.kind == SWITCH:
            options.append(argument.flag)
        elif argument.positional:
            positionals += [str(one) for one in _listed(value)]
        else:
            options += [f"{argument.flag}={one}" for one in _listed(value)]
    return [*item.path, *options, *positionals]


def parsed(item: Verb, values: Mapping[str, Any]) -> argparse.Namespace:
    held: dict[str, str] = {}
    safe: dict[str, Any] = {}
    for argument in item.arguments:
        value = values.get(argument.key)
        if argument.positional and not absent(value):
            safe[argument.key] = [_stand_in(one, held) for one in _listed(value)]
        else:
            safe[argument.key] = value
    args = parser().parse_args(words(item, safe))
    for argument in item.arguments:
        if argument.positional:
            _restore(args, argument.dest, held)
    return args


def shown(program: str, item: Verb, values: Mapping[str, Any]) -> str:
    command = words(item, values)
    dashed = any(
        str(one).startswith("-")
        for argument in item.arguments
        if argument.positional and not absent(values.get(argument.key))
        for one in _listed(values[argument.key])
    )
    if dashed:
        count = sum(
            len(_listed(values[argument.key]))
            for argument in item.arguments
            if argument.positional and not absent(values.get(argument.key))
        )
        command = [
            *command[: len(command) - count],
            "--",
            *command[len(command) - count :],
        ]
    return " ".join(shlex.quote(word) for word in [program, *command])


def _stand_in(value: Any, held: dict[str, str]) -> str:
    text = str(value)
    if not text.startswith("-"):
        return text
    stand_in = PLACEHOLDER.format(index=len(held))
    held[stand_in] = text
    return stand_in


def _restore(args: argparse.Namespace, dest: str, held: Mapping[str, str]) -> None:
    current = getattr(args, dest, None)
    if isinstance(current, list):
        setattr(args, dest, [held.get(one, one) for one in current])
    elif isinstance(current, str):
        setattr(args, dest, held.get(current, current))


def absent(value: Any) -> bool:
    return value is None or value is False or value == "" or value == []


def _listed(value: Any) -> list:
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _walk(
    node: argparse.ArgumentParser, path: tuple, help_text: str, found: list[Verb]
) -> None:
    branches = [
        action
        for action in node._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    if branches:
        helps = {
            choice.dest: choice.help or "" for choice in branches[0]._choices_actions
        }
        for name, child in branches[0].choices.items():
            _walk(child, (*path, name), helps.get(name, ""), found)
        return
    groups = {
        id(action): index
        for index, group in enumerate(node._mutually_exclusive_groups)
        for action in group._group_actions
    }
    arguments = tuple(
        _argument(action, groups.get(id(action)))
        for action in node._actions
        if not isinstance(action, argparse._HelpAction)
    )
    found.append(Verb(path, help_text, node.get_default("handler"), arguments))


def _argument(action: argparse.Action, group: Any) -> Argument:
    flag = action.option_strings[-1] if action.option_strings else ""
    if action.nargs == 0:
        kind = SWITCH
    elif isinstance(action, argparse._AppendAction) or action.nargs == "*":
        kind = MANY
    else:
        kind = VALUE
    required = action.required if flag else action.nargs not in ("?", "*")
    return Argument(
        key=flag or f"<{action.dest}>",
        dest=action.dest,
        flag=flag,
        kind=kind,
        help=action.help or "",
        choices=tuple(str(choice) for choice in action.choices or ()),
        required=required,
        default=action.default,
        group=group,
        number=action.type is int,
    )
