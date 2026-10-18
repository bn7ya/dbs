from __future__ import annotations

import ipaddress
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from dbs.conf import setting

from .paths import HOME_ENV

SETTINGS_MODULE = "dbs.manager.settings"
DATABASE_URL_ENV = "DBS_MANAGER_DATABASE_URL"
HOST_ENV = "DBS_MANAGER_HOST"
TRUSTED_PROXY_ENV = "DBS_MANAGER_TRUSTED_PROXY"
TERMINAL_ENV = "DBS_MANAGER_TERMINAL"
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
    "TERMINAL_ENV",
    "TRUSTED_PROXY_ENV",
    "data_dir",
    "inline_jobs",
    "is_loopback",
    "jobs_inline",
]

INLINE = ContextVar("dbs_manager_jobs_inline", default=False)


def data_dir():
    return Path(setting("DBS_MANAGER_DATA_DIR", "."))


def jobs_inline():
    return INLINE.get() or bool(setting("DBS_MANAGER_JOBS_INLINE", False))


@contextmanager
def inline_jobs() -> Iterator[None]:
    token = INLINE.set(True)
    try:
        yield
    finally:
        INLINE.reset(token)


def is_loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False
