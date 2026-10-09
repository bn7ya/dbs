from __future__ import annotations

import base64
import getpass
import glob
import hashlib
import os
import socket
import sys

from .conf import setting

HOST_KEY_GLOB = "/etc/ssh/ssh_host_*_key.pub"
FORMAT = 1


def fingerprint(blob):
    digest = hashlib.sha256(blob).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def host_keys(pattern=HOST_KEY_GLOB):
    keys = []
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, encoding="ascii") as fh:
                kind, encoded = fh.read().split()[:2]
            keys.append({"type": kind, "fingerprint": fingerprint(base64.b64decode(encoded))})
        except (OSError, ValueError):
            continue
    return keys


def project_dir():
    base = setting("BASE_DIR", None)
    return str(base) if base else os.getcwd()


def manage_path(directory):
    candidate = os.path.join(directory, "manage.py")
    if os.path.isfile(candidate):
        return candidate
    invoked = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    return invoked if os.path.basename(invoked) == "manage.py" else ""


def python_path():
    executable = sys.executable or ""
    if os.path.basename(executable).startswith("python"):
        return executable
    for name in ("python3", "python"):
        candidate = os.path.join(sys.prefix, "bin", name)
        if os.path.isfile(candidate):
            return candidate
    return executable


def ssh_user():
    try:
        return getpass.getuser()
    except (KeyError, OSError):
        return ""


def details():
    from . import __version__
    from .schedule_runner import backup_directory

    directory = project_dir()
    env_file = os.path.join(directory, ".env")
    return {
        "dbs_connection": FORMAT,
        "hostname": socket.gethostname(),
        "ssh_user": ssh_user(),
        "project_dir": directory,
        "python_path": python_path(),
        "manage_path": manage_path(directory),
        "settings_module": os.environ.get("DJANGO_SETTINGS_MODULE", ""),
        "remote_backup_dir": backup_directory() or "",
        "file_roots": [str(root) for root in setting("DBS_FILE_ROOTS", None) or ()],
        "env_path": env_file if os.path.isfile(env_file) else "",
        "dbs_version": __version__,
        "host_keys": host_keys(),
    }
