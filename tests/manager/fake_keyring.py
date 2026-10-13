from __future__ import annotations

import json
import os
from pathlib import Path

from keyring.backend import KeyringBackend

STORE_ENV = "DBS_TEST_KEYRING_FILE"


def entry(service: str, username: str) -> str:
    return f"{service}|{username}"


def entries_in(path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


class FileKeyring(KeyringBackend):
    priority = 1

    def _path(self) -> Path:
        return Path(os.environ[STORE_ENV])

    def get_password(self, service, username):
        return entries_in(self._path()).get(entry(service, username))

    def set_password(self, service, username, password):
        entries = entries_in(self._path())
        entries[entry(service, username)] = password
        self._path().write_text(json.dumps(entries), encoding="utf-8")

    def delete_password(self, service, username):
        entries = entries_in(self._path())
        entries.pop(entry(service, username), None)
        self._path().write_text(json.dumps(entries), encoding="utf-8")


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self) -> None:
        super().__init__()
        self.entries: dict[str, str] = {}
        self.forgetful = False

    def get_password(self, service, username):
        return self.entries.get(entry(service, username))

    def set_password(self, service, username, password):
        if not self.forgetful:
            self.entries[entry(service, username)] = password

    def delete_password(self, service, username):
        self.entries.pop(entry(service, username), None)
