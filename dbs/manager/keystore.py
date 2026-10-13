from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import paths

STORE_ENV = "DBS_MANAGER_KEY_STORE"
FILE = "file"
KEYCHAIN = "keychain"
STORES = (FILE, KEYCHAIN)
SERVICE = "django-dbs-manager"


class KeyStoreError(Exception):
    pass


class KeychainFailed(Exception):
    pass


@dataclass(frozen=True)
class SealingKey:
    value: str
    store: str
    warning: str = ""


def file_warning(data_dir) -> str:
    return (
        f"the manager's sealing key is in {paths.key_path(data_dir)}, next to the data "
        "it protects, because no system keychain works here. Anyone who can read the "
        f"data folder can open the secrets in it. Set ${STORE_ENV}=file to keep it "
        "there knowingly, or install a keychain backend."
    )


def chosen(environ=None) -> str | None:
    environ = os.environ if environ is None else environ
    value = environ.get(STORE_ENV, "").strip().lower()
    if not value:
        return None
    if value not in STORES:
        raise KeyStoreError(f"${STORE_ENV} is file or keychain, not {value!r}.")
    return value


def entry_name(data_dir) -> str:
    return str(Path(data_dir).resolve())


class Keychain:
    def __init__(self, backend) -> None:
        self.backend = backend

    def read(self, name: str) -> str | None:
        try:
            return self.backend.get_password(SERVICE, name)
        except Exception as exc:
            raise KeychainFailed(str(exc) or type(exc).__name__) from exc

    def write(self, name: str, value: str) -> None:
        try:
            self.backend.set_password(SERVICE, name, value)
        except Exception as exc:
            raise KeychainFailed(str(exc) or type(exc).__name__) from exc
        if self.read(name) != value:
            raise KeychainFailed("it did not give the key back")

    def delete(self, name: str) -> None:
        if self.read(name) is None:
            return
        try:
            self.backend.delete_password(SERVICE, name)
        except Exception as exc:
            raise KeychainFailed(str(exc) or type(exc).__name__) from exc


def keychain() -> Keychain | None:
    try:
        import keyring
    except ImportError:
        return None
    try:
        backend = keyring.get_keyring()
        working = backend.priority > 0
    except Exception:
        return None
    return Keychain(backend) if working else None


def load(data_dir, environ=None) -> SealingKey:
    store = chosen(environ)
    if store == FILE:
        return SealingKey(paths.read_key(data_dir), FILE)
    ring = keychain()
    if ring is not None:
        try:
            return _from_keychain(ring, data_dir)
        except KeychainFailed as exc:
            if store == KEYCHAIN or paths.stored_key(data_dir) is None:
                raise KeyStoreError(
                    f"the system keychain refused: {exc}. Unlock it and start again, "
                    f"or set {STORE_ENV}=file to keep the sealing key in a file."
                ) from exc
    elif store == KEYCHAIN:
        raise KeyStoreError(
            f"${STORE_ENV}=keychain, but no system keychain works on this computer."
        )
    return SealingKey(paths.read_key(data_dir), FILE, file_warning(data_dir))


def _from_keychain(ring: Keychain, data_dir) -> SealingKey:
    name = entry_name(data_dir)
    stored = ring.read(name)
    held = paths.stored_key(data_dir)
    if held is None:
        if stored:
            return SealingKey(stored, KEYCHAIN)
        created = paths.new_key()
        ring.write(name, created)
        return SealingKey(created, KEYCHAIN)
    imported = paths.import_marker_path(data_dir).exists()
    if stored and stored != held and not imported:
        raise KeyStoreError(
            f"{paths.key_path(data_dir)} and the system keychain hold different "
            f"sealing keys for {data_dir}. Nothing was changed. Set {STORE_ENV}=file "
            "to use the file, or move the file out of the data folder to use the "
            "keychain's key."
        )
    if stored != held:
        ring.write(name, held)
    paths.key_path(data_dir).unlink()
    paths.clear_import_marker(data_dir)
    return SealingKey(held, KEYCHAIN)


def location(data_dir, environ=None) -> str:
    key_file = paths.key_path(data_dir)
    if key_file.exists() or chosen(environ) == FILE:
        return str(key_file)
    ring = keychain()
    if ring is None:
        return str(key_file)
    return f"system keychain ({SERVICE}: {entry_name(data_dir)})"


def carry(source_dir, target_dir, environ=None) -> None:
    ring = keychain()
    if ring is None or chosen(environ) == FILE:
        return
    try:
        held = ring.read(entry_name(source_dir))
        if held is not None:
            ring.write(entry_name(target_dir), held)
    except KeychainFailed as exc:
        raise KeyStoreError(f"the system keychain refused: {exc}.") from exc


def forget(data_dir, environ=None) -> None:
    ring = keychain()
    if ring is None or chosen(environ) == FILE:
        return
    try:
        ring.delete(entry_name(data_dir))
    except KeychainFailed as exc:
        raise KeyStoreError(f"the system keychain refused: {exc}.") from exc
