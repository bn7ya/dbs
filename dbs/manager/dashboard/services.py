from __future__ import annotations

import shutil
from datetime import timedelta
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import connection
from django.utils import timezone

from dbs import transactions
from dbs.manager import conf, selfupdate
from dbs.manager.accounts.services import AccountService
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.activity.services import ActivityService
from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.repositories import BackupFileRepository, BackupPlanRepository
from dbs.manager.applications.services import ApplicationService
from dbs.manager.dashboard.exceptions import UpdateBusy, UpdateFromTerminal, UpdateRefused
from dbs.manager.permissions import Capability, requires
from dbs.manager.servers.services import ServerService
from dbs.manager.servers.versions import local_version
from dbs.manager.shell.sessions import SHELLS

EXPORT = "manager.export"
UPDATE = "manager.update"
FAILURE_WINDOW = timedelta(days=7)
RECENT_FAILURES = 10
LOW_DISK_BYTES = 1024**3
LOW_DISK_SHARE = 0.05


class DashboardService:
    def __init__(self, user: Any) -> None:
        self.user = user
        self.servers = ServerService(user)
        self.applications = ApplicationService(user)
        self.files = BackupFileRepository()
        self.plans = BackupPlanRepository()
        self.entries = ActivityRepository()
        self.activity = ActivityService(user)

    def summary(self) -> dict[str, Any]:
        with transactions.reading():
            servers = list(self.servers.list())
            applications = list(self.applications.list())
        stored = self.files.stored_bytes_by_application()
        following = self.plans.next_runs_by_application()
        failures = self.entries.failures_by_subject(
            [str(application.pk) for application in applications],
            timezone.now() - FAILURE_WINDOW,
        )
        recent = self.entries.recent_failures(RECENT_FAILURES)
        grouped: dict[Any, list[dict[str, Any]]] = {}
        for application in applications:
            grouped.setdefault(application.server_id, []).append(
                {
                    "id": str(application.pk),
                    "name": application.name,
                    "kind": application.kind,
                    "engine": application.engine,
                    "check_status": application.last_check_status,
                    "checked_at": application.last_checked_at,
                    "last_backup": self._last_backup(application),
                    "next_plan_run": following.get(application.pk),
                    "failures_7d": failures.get(str(application.pk), 0),
                    "storage_bytes": stored.get(application.pk, 0),
                    "health": application.last_health,
                }
            )
        return {
            "servers": [
                {
                    "id": str(server.pk),
                    "name": server.name,
                    "host": server.host,
                    "check_status": server.last_check_status,
                    "checked_at": server.last_checked_at,
                    "connection_state": server.connection_state,
                    "last_seen_at": server.last_seen_at,
                    "applications": grouped.get(server.pk, []),
                }
                for server in servers
            ],
            "storage_bytes": sum(stored.values()),
            "disk": disk_space(settings.BACKUP_STORAGE_DIR),
            "last_export_at": self.last_export_at(),
            "recent_failures": recent,
            "recent_failure_subjects": self.activity.subjects_for(recent),
            "key_store": key_store(),
        }

    def about(self) -> dict[str, Any]:
        return {
            "version": local_version(),
            "data_dir": str(conf.data_dir()),
            "database": describe_database(),
            "backups_dir": str(settings.BACKUP_STORAGE_DIR),
            "last_export_at": self.last_export_at(),
            "key_store": key_store(),
            "max_backups": conf.backup_keep_max(),
        }

    def last_export_at(self):
        export = self.entries.latest_success(EXPORT)
        if export is None:
            return None
        return export.finished_at or export.created_at

    def _last_backup(self, application: Any) -> dict[str, Any] | None:
        file = self.files.latest_of_kind(application.pk, BackupFile.Kind.DBS)
        if file is None:
            return None
        return {
            "id": str(file.pk),
            "name": file.name,
            "size": file.size,
            "created_at": file.created_at,
            "validation": file.validation,
        }


def disk_space(folder: str) -> dict[str, Any] | None:
    place = Path(folder)
    while not place.exists() and place != place.parent:
        place = place.parent
    try:
        usage = shutil.disk_usage(place)
    except OSError:
        return None
    return {
        "total_bytes": usage.total,
        "free_bytes": usage.free,
        "low": usage.free < max(LOW_DISK_BYTES, usage.total * LOW_DISK_SHARE),
    }


def key_store() -> str:
    return getattr(settings, "DBS_MANAGER_KEY_STORE", "file")


def describe_database() -> str:
    database = connection.settings_dict
    if connection.vendor == "sqlite":
        return f"sqlite:{database['NAME']}"
    host = database.get("HOST") or "localhost"
    port = f":{database['PORT']}" if database.get("PORT") else ""
    return f"{connection.vendor}://{host}{port}/{database['NAME']}"


class ManagerUpdateService:
    def __init__(self, user: Any) -> None:
        self.user = user

    @requires(Capability.MANAGER_UPDATE)
    def status(self) -> dict[str, Any]:
        return {**selfupdate.status(), "busy": self.busy()}

    @requires(Capability.MANAGER_UPDATE)
    def update(self, *, password: str, to: str = "") -> dict[str, Any]:
        AccountService(self.user).confirm_password(password)
        if not selfupdate.RESTART.armed:
            raise UpdateFromTerminal()
        if self.busy():
            raise UpdateBusy()
        try:
            planned = selfupdate.plan(to)
        except selfupdate.Refused as refused:
            raise UpdateRefused(refused.code, str(refused)) from refused
        if not planned.needed:
            return {"version": planned.current, "updated": False, "restarting": False}
        with ActivityService(self.user).track(UPDATE, target=planned.target) as entry:
            entry.detail = {"from": planned.current, "to": planned.target}
            try:
                selfupdate.install(planned)
            except selfupdate.Refused as refused:
                raise UpdateRefused(refused.code, str(refused)) from refused
        return {
            "version": planned.target,
            "updated": True,
            "restarting": selfupdate.RESTART.request(),
        }

    def busy(self) -> bool:
        return bool(ActivityRepository().unfinished_ids()) or bool(SHELLS.every())
