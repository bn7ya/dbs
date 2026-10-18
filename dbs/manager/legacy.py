from __future__ import annotations

import logging
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from . import paths

SERVER = "dbs_manager.server"
APPLICATION = "dbs_manager.application"
POINTING_AT_SERVER = (
    "dbs_manager.backupplan",
    "dbs_manager.backupfile",
    "dbs_manager.envversion",
)
LEGACY_FIELD = "runtime"
PROJECT_FIELDS = (LEGACY_FIELD, "python_path", "remote_backup_dir")
SHARED_FIELDS = ("name", "created_by", "created_at", "updated_at", "deleted_at")
SSH_FIELDS = (
    "host",
    "port",
    "username",
    "auth_method",
    "private_key_sealed",
    "key_passphrase_sealed",
    "password_sealed",
    "host_key",
    "host_key_fingerprint",
    "timeout_on_host",
    "connection_state",
    "last_seen_at",
    "last_connection_error",
)
SPLIT_MIGRATION = ("dbs_manager", "0008_application")
COPY_SUFFIX = ".pre-0.8.0"

logger = logging.getLogger("dbs.manager")


class SplitServers:
    def labels(self, order: list) -> list:
        if SERVER not in order or APPLICATION in order:
            return order
        after = order.index(SERVER) + 1
        return [*order[:after], APPLICATION, *order[after:]]

    def records(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        label = record.get("model")
        fields = record.get("fields") or {}
        if label == SERVER and any(name in fields for name in PROJECT_FIELDS):
            return split(record)
        if label in POINTING_AT_SERVER and "server" in fields:
            moved = {name: value for name, value in fields.items() if name != "server"}
            return [{**record, "fields": {**moved, "application": fields["server"]}}]
        return [record]


def split(record: dict[str, Any]) -> list[dict[str, Any]]:
    fields = record["fields"]
    server_id = str(uuid.uuid4())
    in_compose = fields.get(LEGACY_FIELD) == "compose"
    server_fields = {
        name: fields[name] for name in (*SHARED_FIELDS, *SSH_FIELDS) if name in fields
    }
    application_fields = {
        name: value
        for name, value in fields.items()
        if name not in SSH_FIELDS and name != LEGACY_FIELD
    }
    application_fields.update(
        server=server_id,
        kind="compose" if in_compose else "host",
        engine="docker" if in_compose else "",
    )
    return [
        {"model": SERVER, "pk": server_id, "fields": server_fields},
        {**record, "model": APPLICATION, "fields": application_fields},
    ]


def preserve_before_split() -> Path | None:
    from django.db import connection
    from django.db.migrations.recorder import MigrationRecorder

    recorder = MigrationRecorder(connection)
    if not recorder.has_table():
        return None
    applied = set(recorder.applied_migrations())
    if SPLIT_MIGRATION in applied or not any(
        app == SPLIT_MIGRATION[0] for app, _ in applied
    ):
        return None
    if connection.vendor != "sqlite":
        logger.warning(
            "the manager's tables change shape in 0.8.0; keep a backup of its "
            "database to go back to 0.7"
        )
        return None
    source = Path(connection.settings_dict["NAME"])
    copy = source.with_name(source.name + COPY_SUFFIX)
    if copy.exists():
        return copy
    partial = source.with_name(f".{copy.name}.part-{uuid.uuid4().hex[:16]}")
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, paths.FILE_MODE)
    os.close(descriptor)
    try:
        connection.ensure_connection()
        target = sqlite3.connect(str(partial))
        try:
            connection.connection.backup(target)
        finally:
            target.close()
        os.link(partial, copy)
    finally:
        partial.unlink(missing_ok=True)
    return copy
