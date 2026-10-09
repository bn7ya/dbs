from __future__ import annotations

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from dbs.manager.common.models import BaseModel

PLAN_KEEP_MAX = 365
PLAN_PATHS_MAX = 50
PLAN_PATH_MAX_LENGTH = 1024
PLAN_PATTERN_MAX_LENGTH = 200


class PlanKind(models.TextChoices):
    DBS = "dbs", "django-dbs backup"
    ARCHIVE = "archive", "Archive of server folders"
    COLLECT = "collect", "Files a server already makes"


class BackupPlan(BaseModel):
    Kind = PlanKind

    class LastStatus(models.TextChoices):
        NONE = "none", "Not run yet"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    server = models.ForeignKey(
        "dbs_manager.Server",
        on_delete=models.PROTECT,
        related_name="+",
        db_index=False,
    )
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    paths = models.JSONField(default=list, blank=True)
    pattern = models.CharField(
        max_length=PLAN_PATTERN_MAX_LENGTH, blank=True, default=""
    )
    interval_minutes = models.PositiveIntegerField(null=True, blank=True)
    keep = models.PositiveSmallIntegerField(
        default=7, validators=[MinValueValidator(1), MaxValueValidator(PLAN_KEEP_MAX)]
    )
    keep_remote = models.PositiveSmallIntegerField(
        default=1, validators=[MaxValueValidator(PLAN_KEEP_MAX)]
    )
    enabled = models.BooleanField(default=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(
        max_length=16, choices=LastStatus.choices, default=LastStatus.NONE
    )
    last_error_code = models.CharField(max_length=64, blank=True)

    class Meta(BaseModel.Meta):
        indexes = [
            models.Index(
                fields=["enabled", "next_run_at"], name="dbs_manager_plan_due_idx"
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["server", "name"],
                condition=Q(deleted_at__isnull=True),
                name="dbs_manager_plan_unique_active_name",
            ),
        ]

    def __str__(self) -> str:
        return self.name
