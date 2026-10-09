from __future__ import annotations

from django.db import models
from django.db.models import Q

from dbs.manager.common.models import BaseModel


class BackupFile(BaseModel):
    class Kind(models.TextChoices):
        DBS = "dbs", "django-dbs backup"
        ARCHIVE = "archive", "Archive of server folders"
        COLLECTED = "collected", "File collected from a server folder"
        UPLOADED = "uploaded", "File uploaded from a browser"

    class Validation(models.TextChoices):
        STRUCTURE_OK = "structure_ok", "Structure checked"
        VERIFIED = "verified", "Verified"
        FAILED = "failed", "Failed"

    server = models.ForeignKey(
        "dbs_manager.Server",
        on_delete=models.PROTECT,
        related_name="+",
        db_index=False,
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    name = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    storage_path = models.CharField(max_length=512)
    sealed = models.BooleanField(default=False)
    validation = models.CharField(max_length=16, choices=Validation.choices)
    validated_at = models.DateTimeField(null=True, blank=True)
    remote_path = models.CharField(max_length=1024, blank=True)
    remote_size = models.PositiveBigIntegerField(null=True, blank=True)
    remote_mtime = models.DateTimeField(null=True, blank=True)
    removed_at = models.DateTimeField(null=True, blank=True)
    plan = models.ForeignKey(
        "dbs_manager.BackupPlan",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta(BaseModel.Meta):
        indexes = [
            models.Index(
                fields=["server", "-created_at"], name="dbs_manager_backup_server_idx"
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["storage_path"],
                condition=Q(removed_at__isnull=True),
                name="dbs_manager_backup_unique_stored_path",
            ),
        ]

    def __str__(self) -> str:
        return self.name
