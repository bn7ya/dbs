"""The rule the suites hold DBS to: every statement in a transaction, none around a remote call."""

from __future__ import annotations

import functools
import os
import sys
import sysconfig
import threading
from dataclasses import dataclass

from django.db import connections
from django.db.backends.signals import connection_created

import dbs
from dbs.transports import ssh

PACKAGE = os.path.dirname(os.path.abspath(dbs.__file__)) + os.sep
ROOT = os.path.dirname(PACKAGE.rstrip(os.sep)) + os.sep
MIGRATIONS = os.sep + "migrations" + os.sep
LIBRARIES = (
    os.sep + "site-packages" + os.sep,
    sysconfig.get_paths()["stdlib"] + os.sep,
    "<",
)
HANDED_TO_DJANGO = (
    os.path.join("django", "core", "handlers") + os.sep,
    os.path.join("django", "core", "management") + os.sep,
    os.path.join("django", "core", "cache") + os.sep,
    os.path.join("django", "contrib", "auth") + os.sep,
    os.path.join("django", "contrib", "sessions") + os.sep,
)
GENERIC_VIEW_BODIES = os.path.join("rest_framework", "mixins.py")
SCHEMA_EDITORS = os.path.join("django", "db", "backends") + os.sep
NOT_A_QUERY = frozenset(
    {"SAVEPOINT", "RELEASE", "ROLLBACK", "BEGIN", "COMMIT", "PRAGMA", "SET", "SHOW", "START"}
)
TABLE_CHANGES = frozenset({"CREATE", "ALTER", "DROP", "RENAME", "TRUNCATE"})
FLOOR = "_dbs_transaction_floor"
GATEWAY = "dbs.manager.servers.gateways.ssh_gateway"
LOCAL_SESSION_CALLS = frozenset({"close", "is_alive", "path_for"})
WATCHED = "_dbs_transaction_watched"


@dataclass(frozen=True)
class Outside:
    site: str
    verb: str
    alias: str
    thread: str

    def __str__(self):
        return f"{self.verb} on {self.alias!r} at {self.site} ({self.thread})"


@dataclass(frozen=True)
class Held:
    call: str
    site: str
    alias: str
    thread: str

    def __str__(self):
        return (
            f"{self.call} from {self.site} while a transaction is open on "
            f"{self.alias!r} ({self.thread})"
        )


class TransactionRuleBroken(AssertionError):
    def __init__(self, found):
        self.found = list(found)
        outside = [entry for entry in self.found if isinstance(entry, Outside)]
        held = [entry for entry in self.found if isinstance(entry, Held)]
        parts = []
        if outside:
            parts.append(
                "DBS ran these statements outside a transaction. Every statement DBS sends "
                "to a database belongs in dbs.transactions.reading() or atomic():\n"
                + listed(outside)
            )
        if held:
            parts.append(
                "DBS reached a server while a transaction was open. A transaction never "
                "waits for a remote command:\n" + listed(held)
            )
        super().__init__("\n".join(parts))


def listed(entries):
    return "\n".join(f"  {entry}" for entry in dict.fromkeys(map(str, entries)))


class Watch:
    def __init__(self):
        self.found = []
        self.active = False
        self._lock = threading.Lock()

    def start(self):
        watch_the_gateway()
        for connection in connections.all(initialized_only=True):
            attach(connection)
            setattr(connection, FLOOR, depth(connection))
        with self._lock:
            self.found = []
            self.active = True

    def stop(self):
        with self._lock:
            self.active = False
        for connection in connections.all(initialized_only=True):
            setattr(connection, FLOOR, 0)
        return self.taken()

    def taken(self):
        with self._lock:
            found, self.found = self.found, []
        return found

    def note(self, entry):
        with self._lock:
            if self.active:
                self.found.append(entry)


watch = Watch()


def depth(connection):
    return int(connection.in_atomic_block) + len(connection.savepoint_ids)


def in_transaction(connection):
    return depth(connection) > getattr(connection, FLOOR, 0)


def verb_of(sql):
    words = str(sql).split(None, 1)
    return words[0].upper() if words else ""


def in_a_library(path):
    return any(part in path if part[0] == os.sep else path.startswith(part) for part in LIBRARIES)


def described(frame):
    path = frame.f_code.co_filename
    return f"{path[len(ROOT):]}:{frame.f_lineno} in {frame.f_code.co_name}"


def changes_a_table(path):
    return SCHEMA_EDITORS in path and path.endswith("schema.py")


def issuer(frame, connection):
    while frame is not None:
        path = frame.f_code.co_filename
        if path.startswith(PACKAGE):
            return None if MIGRATIONS in path else described(frame)
        if any(part in path for part in HANDED_TO_DJANGO):
            return None
        if changes_a_table(path) and not connection.features.can_rollback_ddl:
            return None
        if path.endswith(GENERIC_VIEW_BODIES):
            view = type(frame.f_locals.get("self"))
            if view.__module__.startswith("dbs."):
                return f"{view.__module__}.{view.__qualname__}.{frame.f_code.co_name}"
        if not in_a_library(path):
            return None
        frame = frame.f_back
    return None


def caller(frame):
    while frame is not None:
        path = frame.f_code.co_filename
        if path.startswith(PACKAGE) and not path.endswith(("ssh.py", "ssh_gateway.py")):
            return described(frame)
        frame = frame.f_back
    return "outside dbs"


class Guard:
    def __init__(self, connection):
        self.connection = connection

    def __call__(self, execute, sql, params, many, context):
        if watch.active and not in_transaction(self.connection):
            verb = verb_of(sql)
            if verb and verb not in NOT_A_QUERY and self.can_be_rolled_back(verb):
                site = issuer(sys._getframe(1), self.connection)
                if site is not None:
                    watch.note(
                        Outside(
                            site, verb, self.connection.alias, threading.current_thread().name
                        )
                    )
        return execute(sql, params, many, context)

    def can_be_rolled_back(self, verb):
        return verb not in TABLE_CHANGES or self.connection.features.can_rollback_ddl


def attach(connection):
    if not any(isinstance(wrapper, Guard) for wrapper in connection.execute_wrappers):
        connection.execute_wrappers.append(Guard(connection))


def attach_to_new(sender, connection, **kwargs):
    attach(connection)


def remote(name, call):
    @functools.wraps(call)
    def checked(*args, **kwargs):
        if watch.active:
            for connection in connections.all(initialized_only=True):
                if in_transaction(connection):
                    watch.note(
                        Held(
                            name,
                            caller(sys._getframe(1)),
                            connection.alias,
                            threading.current_thread().name,
                        )
                    )
        return call(*args, **kwargs)

    return checked


def watch_calls_of(owner, skipped=frozenset()):
    if vars(owner).get(WATCHED):
        return
    for name, member in list(vars(owner).items()):
        if name.startswith("_") or name in skipped or not callable(member):
            continue
        if isinstance(member, (staticmethod, classmethod, property, type)):
            continue
        setattr(owner, name, remote(f"{owner.__name__}.{name}", member))
    setattr(owner, WATCHED, True)


def watch_the_gateway():
    gateway = sys.modules.get(GATEWAY)
    if gateway is not None:
        watch_calls_of(gateway.RemoteHost)


def install():
    connection_created.connect(attach_to_new, weak=False, dispatch_uid="dbs-transaction-guard")
    watch_calls_of(ssh.SSHSession, LOCAL_SESSION_CALLS)


def fail(outcome, found):
    error = TransactionRuleBroken(found)
    if hasattr(outcome, "force_exception"):
        outcome.force_exception(error)
    else:
        raise error
