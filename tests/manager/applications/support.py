from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dbs.manager.applications.services.discovery_service import (
    FIND_PROJECT,
    INSPECTED_FIELDS,
    json_rows,
)
from dbs.manager.servers.services.pythons import VERSION_PROBE

FIXTURES = Path(__file__).parent / "fixtures"
TEMPLATE_JSON_FIELD = re.compile(r"\{\{json \.([\w.]+)\}\}")
HOST_MARK = "${HOST}"
SERVER_HOST = "10.0.0.5"
VERSION_FORMATS = {"docker": "{{.Server.Version}}", "podman": "{{.Version}}"}
VALUED_FLAGS = ("-u", "-w", "-e")


def fixture(name: str, root: Path) -> str:
    return (FIXTURES / name).read_text().replace(HOST_MARK, str(root))


@dataclass
class Inside:
    root: Path
    pythons: dict[str, str] = field(default_factory=dict)
    connection: dict | None = None
    ran: list[list[str]] = field(default_factory=list)

    def answer(self, command: list[str]) -> tuple[int, str, str]:
        self.ran.append(command)
        python = command[0]
        if command[1:3] == ["-c", VERSION_PROBE] and len(command) == 3:
            if python in self.pythons:
                return 0, f"{self.pythons[python]}\n", ""
            return 127, "", f'exec: "{python}": executable file not found in $PATH'
        if python not in self.pythons:
            return 127, "", f'exec: "{python}": executable file not found in $PATH'
        if command[1:3] == ["-c", FIND_PROJECT]:
            return self.find_project(command[3:])
        if command[2:] == ["dbs", "connection", "--json"]:
            if self.connection is None:
                return 1, "", "Unknown command: 'dbs'"
            return 0, json.dumps(self.connection), ""
        return 1, "", f"unexpected command {command}"

    def find_project(self, starts: list[str]) -> tuple[int, str, str]:
        mapped = [str(self.root / start.lstrip("/")) for start in starts]
        done = subprocess.run(
            [sys.executable, "-c", FIND_PROJECT, *mapped],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        return done.returncode, done.stdout.replace(str(self.root), ""), done.stderr


class Engines:
    def __init__(self, hosts, root: Path, host: str = SERVER_HOST) -> None:
        self.hosts = hosts
        self.root = root
        self.host = host
        self.containers: dict[str, Inside] = {}
        self.inspected: list[list[str]] = []

    def answer(self, argv: list[str], result) -> None:
        self.hosts.answer(self.host, argv, result)

    def offer(
        self,
        engine: str,
        *,
        version: str,
        compose: str | None = None,
        ps: str,
        inspect: str,
    ) -> list[dict]:
        rows = json.loads(fixture(inspect, self.root))
        self.answer(
            [engine, "version", "--format", VERSION_FORMATS[engine]],
            (0, f"{version}\n", ""),
        )
        if compose is not None:
            self.answer(
                [engine, "compose", "version", "--short"], (0, f"{compose}\n", "")
            )
        self.answer(
            [engine, "ps", "--all", "--no-trunc", "--format", "{{.ID}}"],
            (0, listed_ids(fixture(ps, self.root)), ""),
        )
        self.answer([engine, "inspect"], self.inspecting(rows))
        self.answer([engine, "exec"], self.exec)
        self.answer([engine, "compose"], self.exec)
        return rows

    def refuse(self, engine: str, status: int, stderr: str) -> None:
        self.answer(
            [engine, "version", "--format", VERSION_FORMATS[engine]],
            (status, "", stderr),
        )

    def place(self, name: str, inside: Inside) -> Inside:
        self.containers[name] = inside
        return inside

    def inspecting(self, rows: list[dict]):
        def inspect(argv, stdin_line):
            assert argv[2:6] == ["--type", "container", "--format", INSPECTED_FIELDS]
            asked = argv[6:]
            self.inspected.append(asked)
            by_id = {row["Id"]: row for row in rows}
            return (
                0,
                "".join(
                    rendered(INSPECTED_FIELDS, by_id[identifier]) + "\n"
                    for identifier in asked
                    if identifier in by_id
                ),
                "",
            )

        return inspect

    def exec(self, argv, stdin_line):
        if argv[1:3] == ["compose", "version"]:
            return 1, "", f"{argv[0]}: 'compose' is not a {argv[0]} command."
        name, command = split_exec(argv)
        inside = self.containers.get(name)
        if inside is None:
            return 1, "", f"Error: no container named {name} is running"
        return inside.answer(command)


def listed_ids(ps_output: str) -> str:
    return "".join(
        f"{row.get('ID') or row['Id']}\n" for row in json_rows(ps_output)
    )


def rendered(template: str, row: dict) -> str:
    def value(match: re.Match) -> str:
        found = row
        for name in match.group(1).split("."):
            found = found.get(name) if isinstance(found, dict) else None
        return json.dumps(found)

    return TEMPLATE_JSON_FIELD.sub(value, template)


def split_exec(argv: list[str]) -> tuple[str, list[str]]:
    if argv[1] == "compose":
        rest = argv[2:]
        while rest[:1] in (["-f"], ["-p"]):
            rest = rest[2:]
        assert rest[0] == "exec", argv
    else:
        assert argv[1] == "exec", argv
        rest = argv[1:]
    rest = rest[1:]
    while rest[0].startswith("-"):
        flag = rest.pop(0)
        if flag in VALUED_FLAGS:
            rest.pop(0)
    return rest[0], rest[1:]
