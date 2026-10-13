from __future__ import annotations

import os
import secrets
import subprocess
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
IMPORT_MARKER = "import.complete"
STAGING_SUFFIX = ".import-"
ASIDE_SUFFIX = ".before-import-"
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


def owner_principal(environ=None):
    environ = os.environ if environ is None else environ
    user = environ.get("USERNAME", "")
    domain = environ.get("USERDOMAIN", "")
    return f"{domain}\\{user}" if domain and user else user


def restrict_to_owner(path, platform=None, environ=None, run=subprocess.run):
    if not (platform or sys.platform).startswith("win"):
        return True
    principal = owner_principal(environ)
    if not principal:
        return False
    try:
        done = run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"{principal}:(OI)(CI)F",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return done.returncode == 0


def ensure_data_dir(data_dir):
    data_dir = Path(data_dir)
    created = not data_dir.exists()
    data_dir = private_directory(data_dir)
    if created and not restrict_to_owner(data_dir):
        print(
            f"Warning: could not limit {data_dir} to your account; check who can read it.",
            file=sys.stderr,
        )
    private_directory(data_dir / KEY_FILE.parent)
    return data_dir


def key_path(data_dir):
    return Path(data_dir) / KEY_FILE


def new_key():
    return secrets.token_urlsafe(KEY_BYTES)


def ensure_key(data_dir):
    path = key_path(data_dir)
    private_directory(path.parent)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
    except FileExistsError:
        return path
    with os.fdopen(descriptor, "w", encoding="ascii") as handle:
        handle.write(new_key())
    return path


def read_key(data_dir):
    return ensure_key(data_dir).read_text(encoding="ascii").strip()


def stored_key(data_dir):
    try:
        held = key_path(data_dir).read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return None
    return held or None


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


def import_marker_path(data_dir):
    return Path(data_dir) / IMPORT_MARKER


def clear_import_marker(data_dir):
    try:
        import_marker_path(data_dir).unlink()
    except FileNotFoundError:
        pass


def staging_path(data_dir, stamp):
    data_dir = Path(data_dir)
    return data_dir.with_name(f"{data_dir.name}{STAGING_SUFFIX}{stamp}")


def aside_path(data_dir, stamp):
    data_dir = Path(data_dir)
    return data_dir.with_name(f"{data_dir.name}{ASIDE_SUFFIX}{stamp}")


def finished_stage(data_dir):
    data_dir = Path(data_dir)
    prefix = f"{data_dir.name}{STAGING_SUFFIX}"
    if not data_dir.parent.is_dir():
        return None
    stages = sorted(
        candidate
        for candidate in data_dir.parent.iterdir()
        if candidate.name.startswith(prefix) and import_marker_path(candidate).exists()
    )
    return stages[-1] if stages else None


def finish_interrupted_import(data_dir):
    data_dir = Path(data_dir)
    if data_dir.exists():
        return None
    stage = finished_stage(data_dir)
    if stage is None:
        return None
    os.replace(stage, data_dir)
    return stage
