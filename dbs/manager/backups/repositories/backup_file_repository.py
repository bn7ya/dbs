from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from django.db.models import F, QuerySet, Sum

from dbs.manager.backups.models import BackupFile
from dbs.manager.common.repositories import BaseRepository


class BackupFileRepository(BaseRepository):
    model = BackupFile

    def active(self) -> QuerySet[BackupFile]:
        return super().active().select_related("server", "plan", "created_by")

    def alive_for_server(self, server_id: UUID) -> QuerySet[BackupFile]:
        return self.active().filter(server_id=server_id).order_by("-created_at", "-id")

    def alive_for_plan(self, plan_id: UUID) -> QuerySet[BackupFile]:
        return (
            self.active()
            .filter(plan_id=plan_id)
            .order_by(
                "-created_at", F("remote_mtime").desc(nulls_last=True), "-name", "-id"
            )
        )

    def collected_from(
        self, plan_id: UUID, remote_paths: Iterable[str]
    ) -> QuerySet[BackupFile, tuple[str, int | None, datetime | None]]:
        return (
            self.all_including_deleted()
            .filter(plan_id=plan_id, remote_path__in=list(remote_paths))
            .values_list("remote_path", "remote_size", "remote_mtime")
        )

    def find_including_deleted(self, file_id: UUID) -> BackupFile | None:
        return (
            self.all_including_deleted()
            .select_related("server", "plan", "created_by")
            .filter(pk=file_id)
            .first()
        )

    def deleted_before(self, moment: datetime) -> QuerySet[BackupFile]:
        return (
            self.all_including_deleted()
            .filter(deleted_at__lt=moment, removed_at__isnull=True)
            .order_by("deleted_at", "id")
        )

    def latest_of_kind(self, server_id: UUID, kind: str) -> BackupFile | None:
        return (
            self.alive_for_server(server_id)
            .filter(kind=kind, removed_at__isnull=True)
            .first()
        )

    def stored_bytes_by_server(self) -> dict[UUID, int]:
        rows = (
            self.all_including_deleted()
            .filter(removed_at__isnull=True)
            .values("server_id")
            .annotate(stored=Sum("size"))
        )
        return {row["server_id"]: row["stored"] or 0 for row in rows}

    def still_stored(self) -> QuerySet:
        return self.all_including_deleted().filter(removed_at__isnull=True)
