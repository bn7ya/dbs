from __future__ import annotations

import ipaddress
from pathlib import Path

from dbs.conf import setting

from .paths import HOME_ENV

SETTINGS_MODULE = "dbs.manager.settings"
DATABASE_URL_ENV = "DBS_MANAGER_DATABASE_URL"
HOST_ENV = "DBS_MANAGER_HOST"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")
INSTANCE_LEASE = "dbs.manager"
SETUP_LEASE = "dbs.manager.setup"
LEASE_SECONDS = 90

__all__ = [
    "DATABASE_URL_ENV",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "HOME_ENV",
    "HOST_ENV",
    "INSTANCE_LEASE",
    "LEASE_SECONDS",
    "LOCAL_HOSTS",
    "SETTINGS_MODULE",
    "SETUP_LEASE",
    "data_dir",
    "is_loopback",
    "jobs_inline",
]


def data_dir():
    return Path(setting("DBS_MANAGER_DATA_DIR", "."))


def jobs_inline():
    return bool(setting("DBS_MANAGER_JOBS_INLINE", False))


def is_loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False
