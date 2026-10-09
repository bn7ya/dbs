from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import connection
from django.utils import timezone

from dbs.manager import conf
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.activity.services import ActivityService
from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.repositories import BackupFileRepository, BackupPlanRepository
from dbs.manager.servers.services import ServerService
from dbs.manager.servers.versions import local_version

EXPORT = "manager.export"
FAILURE_WINDOW = timedelta(days=7)
RECENT_FAILURES = 10


class DashboardService:
    def __init__(self, user: Any) -> None:
        self.user = user
        self.servers = ServerService(user)
        self.files = BackupFileRepository()
        self.plans = BackupPlanRepository()
        self.entries = ActivityRepository()
        self.activity = ActivityService(user)

    def summary(self) -> dict[str, Any]:
        servers = list(self.servers.list())
        stored = self.files.stored_bytes_by_server()
        following = self.plans.next_runs_by_server()
        failures = self.entries.failures_by_subject(
            [str(server.pk) for server in servers], timezone.now() - FAILURE_WINDOW
        )
        recent = self.entries.recent_failures(RECENT_FAILURES)
        return {
            "servers": [
                {
                    "id": str(server.pk),
                    "name": server.name,
                    "host": server.host,
                    "check_status": server.last_check_status,
                    "checked_at": server.last_checked_at,
                    "last_backup": self._last_backup(server),
                    "next_plan_run": following.get(server.pk),
                    "failures_7d": failures.get(str(server.pk), 0),
                    "storage_bytes": stored.get(server.pk, 0),
                    "health": server.last_health,
                }
                for server in servers
            ],
            "storage_bytes": sum(stored.values()),
            "last_export_at": self.last_export_at(),
            "recent_failures": recent,
            "recent_failure_servers": self.activity.servers_for(recent),
        }

    def about(self) -> dict[str, Any]:
        return {
            "version": local_version(),
            "data_dir": str(conf.data_dir()),
            "database": describe_database(),
            "backups_dir": str(settings.BACKUP_STORAGE_DIR),
            "last_export_at": self.last_export_at(),
        }

    def last_export_at(self):
        export = self.entries.latest_success(EXPORT)
        if export is None:
            return None
        return export.finished_at or export.created_at

    def _last_backup(self, server: Any) -> dict[str, Any] | None:
        file = self.files.latest_of_kind(server.pk, BackupFile.Kind.DBS)
        if file is None:
            return None
        return {
            "id": str(file.pk),
            "name": file.name,
            "size": file.size,
            "created_at": file.created_at,
            "validation": file.validation,
        }


def describe_database() -> str:
    database = connection.settings_dict
    if connection.vendor == "sqlite":
        return f"sqlite:{database['NAME']}"
    host = database.get("HOST") or "localhost"
    port = f":{database['PORT']}" if database.get("PORT") else ""
    return f"{connection.vendor}://{host}{port}/{database['NAME']}"
