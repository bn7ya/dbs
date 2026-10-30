from __future__ import annotations

from collections.abc import Mapping
from typing import Any

QUESTIONS: dict[str, tuple[str, ...]] = {
    "runs_in": ("host", "compose", "container"),
    "engine": ("docker", "podman"),
    "database": ("postgresql", "mysql", "mariadb", "sqlite", "other"),
    "database_runs": ("compose", "this_server", "elsewhere", "file"),
    "settings_from": ("folder_env", "compose_env_file", "image", "environment"),
    "source": ("git", "copied", "image"),
    "process_manager": ("systemd", "systemd_user", "supervisor", "other"),
    "web_server": ("nginx", "other", "none"),
}
NOT_SURE = ""
COMPARABLE = ("runs_in", "engine", "database", "database_runs", "settings_from", "source")
SAME_DATABASE = {"mariadb": "mysql"}


def cleaned(answers: Mapping[str, Any] | None) -> dict[str, str]:
    kept: dict[str, str] = {}
    for key, value in (answers or {}).items():
        if key not in QUESTIONS:
            raise ValueError(f"Unknown question: {key!r}")
        if value in (None, NOT_SURE):
            continue
        if value not in QUESTIONS[key]:
            raise ValueError(f"Unknown answer for {key}: {value!r}")
        kept[key] = value
    return kept


def _comparable(key: str, value: str) -> str:
    return SAME_DATABASE.get(value, value) if key == "database" else value


def mismatches(
    said: Mapping[str, str] | None, found: Mapping[str, str] | None
) -> list[dict[str, str]]:
    said = said or {}
    found = found or {}
    return [
        {"field": key, "said": said[key], "found": found[key]}
        for key in COMPARABLE
        if said.get(key)
        and found.get(key)
        and _comparable(key, said[key]) != _comparable(key, found[key])
    ]


def agreements(said: Mapping[str, str] | None, found: Mapping[str, str]) -> int:
    said = said or {}
    return sum(
        1
        for key in COMPARABLE
        if said.get(key)
        and found.get(key)
        and _comparable(key, said[key]) == _comparable(key, found[key])
    )


def effective(
    said: Mapping[str, str] | None, found: Mapping[str, str] | None
) -> dict[str, str]:
    return {**(said or {}), **{k: v for k, v in (found or {}).items() if v}}
