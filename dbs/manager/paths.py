from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

HOME_ENV = "DBS_MANAGER_HOME"
APP_DIRECTORY = "django-dbs"
DIRECTORY_MODE = 0o700
FILE_MODE = 0o600
KEY_FILE = Path("keys") / "secret.key"
DATABASE_FILE = "manager.sqlite3"
LOG_FILE = "manager.log"
INSTANCE_FILE = "manager.json"
SETUP_TOKEN_FILE = "setup.token"
BACKUPS_DIRECTORY = "backups"
KEY_BYTES = 48


def default_data_dir(platform=None, environ=None, home=None):
    platform = platform or sys.platform
    environ = os.environ if environ is None else environ
    home = Path(home) if home is not None else Path.home()
    if platform.startswith("win"):
        base = environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        return Path(base) / APP_DIRECTORY
    if platform == "darwin":
        return home / "Library" / "Application Support" / APP_DIRECTORY
    base = environ.get("XDG_DATA_HOME") or str(home / ".local" / "share")
    return Path(base) / APP_DIRECTORY


def resolve_data_dir(explicit=None, environ=None, platform=None, home=None):
    environ = os.environ if environ is None else environ
    if explicit:
        return Path(explicit).expanduser().resolve()
    configured = environ.get(HOME_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    return default_data_dir(platform=platform, environ=environ, home=home)


def private_directory(path):
    path = Path(path)
    path.mkdir(mode=DIRECTORY_MODE, parents=True, exist_ok=True)
    if os.name == "posix":
        path.chmod(DIRECTORY_MODE)
    return path


def ensure_data_dir(data_dir):
    data_dir = private_directory(data_dir)
    private_directory(data_dir / KEY_FILE.parent)
    return data_dir


def key_path(data_dir):
    return Path(data_dir) / KEY_FILE


def ensure_key(data_dir):
    path = key_path(data_dir)
    private_directory(path.parent)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
    except FileExistsError:
        return path
    with os.fdopen(descriptor, "w", encoding="ascii") as handle:
        handle.write(secrets.token_urlsafe(KEY_BYTES))
    return path


def read_key(data_dir):
    return ensure_key(data_dir).read_text(encoding="ascii").strip()


def write_private(path, text):
    path = Path(path)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
    if os.name == "posix":
        path.chmod(FILE_MODE)
    return path


def database_path(data_dir):
    return Path(data_dir) / DATABASE_FILE


def log_path(data_dir):
    return Path(data_dir) / LOG_FILE


def instance_path(data_dir):
    return Path(data_dir) / INSTANCE_FILE


def setup_token_path(data_dir):
    return Path(data_dir) / SETUP_TOKEN_FILE


def backups_path(data_dir):
    return Path(data_dir) / BACKUPS_DIRECTORY
