"""What 0.8.0 and every later release promised, and how to tell whether a change keeps it."""

from __future__ import annotations

import argparse
import dataclasses
import enum
import importlib
import inspect
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PACKAGE = ROOT / "dbs"
SETTINGS_REFERENCE = ROOT / "docs" / "reference" / "settings.md"
STABILITY_KEY = "dbs-stability-golden-secret-key"

PYTHON_MODULES = {
    "dbs": None,
    "dbs.transports": None,
    "dbs.engine": None,
    "dbs.engine.restore": ("RestoreResult",),
    "dbs.exceptions": None,
}
DESTRUCTIVE_OPERATIONS = (
    "RemoveField",
    "DeleteModel",
    "RenameField",
    "RenameModel",
    "AlterModelTable",
)
OPTIONAL_NARGS = ("?", "*", argparse.REMAINDER)
SETTING_ROW = re.compile(r"^\| `(DBS_[A-Z0-9_]+)` \|(?: ([^|]*) \|)?")
CONVERTER = re.compile(r"<(?:(\w+):)?\w+>")


def releases():
    return sorted(
        (folder for folder in HERE.iterdir() if folder.is_dir() and folder.name[0].isdigit()),
        key=lambda folder: tuple(int(part) for part in folder.name.split(".")),
    )


def recorded(release, part):
    path = release / f"{part}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _default(parameter):
    if parameter.default is inspect.Parameter.empty:
        return None
    text = repr(parameter.default)
    return f"<{type(parameter.default).__name__}>" if " at 0x" in text else text


def signature(target):
    try:
        found = inspect.signature(target)
    except (TypeError, ValueError):
        return None
    return [
        [
            parameter.name,
            parameter.kind.name,
            parameter.default is not inspect.Parameter.empty,
            _default(parameter),
        ]
        for parameter in found.parameters.values()
    ]


def _ours(cls):
    return cls.__module__ == "dbs" or cls.__module__.startswith("dbs.")


def _defining(cls, name):
    return next((owner for owner in cls.__mro__ if name in vars(owner)), None)


def _member(cls, name):
    raw = vars(_defining(cls, name))[name]
    if isinstance(raw, property):
        return {"kind": "property"}
    if isinstance(raw, (staticmethod, classmethod)) or inspect.isfunction(raw):
        return {"kind": "method", "signature": signature(getattr(cls, name))}
    return {"kind": "attribute"}


def describe(value):
    if inspect.isclass(value):
        entry = {
            "kind": "class",
            "bases": [base.__name__ for base in value.__mro__[1:] if base is not object],
            "members": {},
        }
        if not issubclass(value, enum.Enum) and any(
            _ours(owner) and ("__init__" in vars(owner) or "__new__" in vars(owner))
            for owner in value.__mro__
        ):
            entry["init"] = signature(value)
        for name in dir(value):
            owner = _defining(value, name)
            if name.startswith("_") or owner is None or not _ours(owner):
                continue
            if issubclass(value, enum.Enum) and name in value.__members__:
                continue
            entry["members"][name] = _member(value, name)
        if dataclasses.is_dataclass(value):
            entry["fields"] = [field.name for field in dataclasses.fields(value)]
        if issubclass(value, enum.Enum):
            entry["enum"] = {name: repr(member.value) for name, member in value.__members__.items()}
        return entry
    if inspect.isfunction(value) or inspect.isbuiltin(value):
        return {"kind": "function", "signature": signature(value)}
    if isinstance(value, (str, int, float, bool)):
        return {"kind": "value"}
    return {"kind": "instance", "type": type(value).__name__}


def _public_names(module, names):
    if names is not None:
        return names
    exported = getattr(module, "__all__", None)
    if exported is not None:
        return exported
    return sorted(
        name
        for name, value in vars(module).items()
        if not name.startswith("_") and inspect.isclass(value) and value.__module__ == module.__name__
    )


def python_surface():
    surface = {}
    for module_name, names in PYTHON_MODULES.items():
        module = importlib.import_module(module_name)
        surface[module_name] = {
            name: describe(getattr(module, name)) for name in _public_names(module, names)
        }
    return surface


def _required(action):
    if action.option_strings:
        return bool(action.required)
    return action.nargs not in OPTIONAL_NARGS


def parser_tree(parser, ignored=frozenset(), path=""):
    tree = {}
    entry = {"options": {}, "positionals": []}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                tree.update(parser_tree(child, ignored, f"{path} {name}".strip()))
        elif action.option_strings:
            for option in action.option_strings:
                if option in ignored:
                    continue
                entry["options"][option] = {
                    "value": action.nargs != 0,
                    "required": _required(action),
                    "choices": None
                    if action.choices is None
                    else sorted(str(choice) for choice in action.choices),
                }
        else:
            entry["positionals"].append({"required": _required(action)})
    tree[path] = entry
    return tree


def django_default_options():
    from django.core.management.base import BaseCommand

    parser = BaseCommand().create_parser("manage.py", "stability")
    return frozenset(
        option for action in parser._actions for option in action.option_strings
    )


def command_surface():
    from django.core.management import get_commands, load_command_class

    parser = load_command_class("dbs", "dbs").create_parser("manage.py", "dbs")
    return {
        "names": sorted(name for name, app in get_commands().items() if app == "dbs"),
        "tree": parser_tree(parser, django_default_options()),
    }


def documented_settings():
    found = {}
    for line in SETTINGS_REFERENCE.read_text(encoding="utf-8").splitlines():
        match = SETTING_ROW.match(line)
        if match:
            found[match.group(1)] = (match.group(2) or "").strip()
    return found


def package_source():
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(PACKAGE.rglob("*.py"))
    )


def migration_names(app_label):
    from django.db.migrations.loader import MigrationLoader

    loader = MigrationLoader(None, ignore_no_migrations=True)
    return sorted(name for app, name in loader.disk_migrations if app == app_label)


def destructive_migrations(app_label, released):
    from django.db.migrations.loader import MigrationLoader

    loader = MigrationLoader(None, ignore_no_migrations=True)
    found = []
    for (app, name), migration in loader.disk_migrations.items():
        if app != app_label or name in released:
            continue
        for operation in migration.operations:
            if type(operation).__name__ in DESTRUCTIVE_OPERATIONS:
                found.append(f"{app}.{name}: {type(operation).__name__}")
    return sorted(found)


def released_migrations_missing(app_label, released):
    from django.db.migrations.loader import MigrationLoader

    loader = MigrationLoader(None, ignore_no_migrations=True)
    present = {name for app, name in loader.disk_migrations if app == app_label}
    for (app, _), migration in loader.disk_migrations.items():
        if app == app_label:
            present.update(name for label, name in migration.replaces if label == app_label)
    return sorted(set(released) - present)


def route_surface(urlconf):
    from django.urls import URLPattern, URLResolver, get_resolver
    from django.urls.resolvers import RoutePattern

    routes = {}

    def walk(patterns, prefix):
        for pattern in patterns:
            text = prefix + str(pattern.pattern)
            if isinstance(pattern, URLResolver):
                walk(pattern.url_patterns, text)
            elif isinstance(pattern.pattern, RoutePattern):
                routes[CONVERTER.sub(lambda m: f"<{m.group(1) or 'str'}>", text)] = _methods(
                    pattern.callback
                )
            elif isinstance(pattern, URLPattern):
                routes[text] = _methods(pattern.callback)

    walk(get_resolver(urlconf).url_patterns, "")
    return routes


def _methods(callback):
    actions = getattr(callback, "actions", None)
    if actions:
        return sorted(actions)
    view = getattr(callback, "view_class", None)
    if view is None:
        return []
    return sorted(
        method
        for method in view.http_method_names
        if method not in ("head", "options", "trace") and hasattr(view, method)
    )


def missing(recorded_names, current_names, what):
    return [f"{what} {name!r} is gone" for name in recorded_names if name not in current_names]


def signature_changes(where, before, now):
    if before is None:
        return []
    if now is None:
        return [f"{where} no longer has a signature"]
    problems = []
    current = {parameter[0]: (index, parameter) for index, parameter in enumerate(now)}
    for index, (name, kind, has_default, default) in enumerate(before):
        if name not in current:
            problems.append(f"{where}: parameter {name!r} was removed")
            continue
        position, (_, now_kind, now_has_default, now_default) = current[name]
        if now_kind != kind:
            problems.append(f"{where}: parameter {name!r} changed from {kind} to {now_kind}")
        elif kind in ("POSITIONAL_ONLY", "POSITIONAL_OR_KEYWORD") and position != index:
            problems.append(f"{where}: parameter {name!r} moved from position {index} to {position}")
        if has_default and (not now_has_default or now_default != default):
            problems.append(f"{where}: parameter {name!r} changed its default from {default}")
    known = {parameter[0] for parameter in before}
    for name, kind, has_default, _ in now:
        if name not in known and not has_default and kind not in ("VAR_POSITIONAL", "VAR_KEYWORD"):
            problems.append(f"{where}: new parameter {name!r} has no default")
    return problems


def describe_changes(where, before, now):
    if now is None:
        return [f"{where} is gone"]
    if now["kind"] != before["kind"]:
        return [f"{where} changed from a {before['kind']} to a {now['kind']}"]
    problems = []
    if "signature" in before:
        problems += signature_changes(where, before["signature"], now.get("signature"))
    if "init" in before:
        problems += signature_changes(f"{where}()", before["init"], now.get("init"))
    if before["kind"] == "instance" and before["type"] != now["type"]:
        problems.append(f"{where} is no longer a {before['type']}")
    problems += missing(before.get("bases", ()), now.get("bases", ()), f"{where}: base class")
    problems += missing(before.get("fields", ()), now.get("fields", ()), f"{where}: field")
    for name, member in before.get("members", {}).items():
        problems += describe_changes(f"{where}.{name}", member, now.get("members", {}).get(name))
    for name, value in before.get("enum", {}).items():
        if now.get("enum", {}).get(name) != value:
            problems.append(f"{where}.{name} no longer equals {value}")
    return problems


def python_changes(before, now):
    problems = []
    for module, names in before.items():
        for name, entry in names.items():
            problems += describe_changes(f"{module}.{name}", entry, now.get(module, {}).get(name))
    return problems


def parser_changes(what, before, now):
    problems = []
    for path, entry in before.items():
        label = f"{what} {path}".strip()
        current = now.get(path)
        if current is None:
            problems.append(f"{label} is gone")
            continue
        for option, info in entry["options"].items():
            found = current["options"].get(option)
            if found is None:
                problems.append(f"{label}: {option} is gone")
                continue
            if found["value"] != info["value"]:
                problems.append(f"{label}: {option} changed whether it takes a value")
            if found["required"] and not info["required"]:
                problems.append(f"{label}: {option} became required")
            if found["choices"] is not None and (
                info["choices"] is None or set(info["choices"]) - set(found["choices"])
            ):
                problems.append(f"{label}: {option} accepts fewer values")
        for option, info in current["options"].items():
            if option not in entry["options"] and info["required"]:
                problems.append(f"{label}: new option {option} is required")
        positionals = current["positionals"]
        if len(positionals) < len(entry["positionals"]):
            problems.append(f"{label} takes fewer arguments")
        for index, info in enumerate(entry["positionals"][: len(positionals)]):
            if positionals[index]["required"] and not info["required"]:
                problems.append(f"{label}: argument {index + 1} became required")
        for index, info in enumerate(positionals[len(entry["positionals"]) :], len(entry["positionals"])):
            if info["required"]:
                problems.append(f"{label}: new argument {index + 1} is required")
    return problems


def schema_changes(where, before, now):
    if now is None:
        return [f"{where} is gone"]
    problems = []
    if before.get("type") != now.get("type"):
        problems.append(f"{where} changed its type from {before.get('type')} to {now.get('type')}")
    if "enum" in now and ("enum" not in before or set(map(str, before["enum"])) - set(map(str, now["enum"]))):
        problems.append(f"{where} accepts fewer values")
    for key in ("minimum", "minLength", "minItems"):
        if now.get(key) is not None and (before.get(key) is None or now[key] > before[key]):
            problems.append(f"{where}: {key} went up")
    for key in ("maximum", "maxLength", "maxItems"):
        if now.get(key) is not None and (before.get(key) is None or now[key] < before[key]):
            problems.append(f"{where}: {key} went down")
    for name in sorted(set(now.get("required", ())) - set(before.get("required", ()))):
        problems.append(f"{where}: {name} became required")
    for name, schema in before.get("properties", {}).items():
        problems += schema_changes(f"{where}.{name}", schema, now.get("properties", {}).get(name))
    if "items" in before:
        problems += schema_changes(f"{where}[]", before["items"], now.get("items"))
    return problems


def route_changes(before, now):
    problems = []
    for route, methods in before.items():
        if route not in now:
            problems.append(f"/{route} is gone")
            continue
        for method in methods:
            if method not in now[route]:
                problems.append(f"{method.upper()} /{route} is gone")
    return problems
