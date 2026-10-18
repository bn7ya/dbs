from __future__ import annotations

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from dbs.manager.common.models import BaseModel

PLAN_KEEP_MIN = 1
PLAN_KEEP_MAX = 5
PLAN_KEEP_REMOTE_MIN = 0
PLAN_KEEP_REMOTE_DEFAULT = 0
PLAN_PATHS_MAX = 50
PLAN_PATH_MAX_LENGTH = 1024
PLAN_PATTERN_MAX_LENGTH = 200
PLAN_TIME_ZONE_MAX_LENGTH = 64
PLAN_DEFAULT_TIME_ZONE = "UTC"


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

    application = models.ForeignKey(
        "dbs_manager.Application",
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
        default=PLAN_KEEP_MAX,
        validators=[
            MinValueValidator(PLAN_KEEP_MIN),
            MaxValueValidator(PLAN_KEEP_MAX),
        ],
    )
    keep_remote = models.PositiveSmallIntegerField(
        default=PLAN_KEEP_REMOTE_DEFAULT,
        validators=[
            MinValueValidator(PLAN_KEEP_REMOTE_MIN),
            MaxValueValidator(PLAN_KEEP_MAX),
        ],
    )
    enabled = models.BooleanField(default=True)
    anchor_at = models.DateTimeField(null=True, blank=True)
    time_zone = models.CharField(
        max_length=PLAN_TIME_ZONE_MAX_LENGTH, default=PLAN_DEFAULT_TIME_ZONE
    )
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
                fields=["application", "name"],
                condition=Q(deleted_at__isnull=True),
                name="dbs_manager_plan_unique_active_name",
            ),
        ]

    def __str__(self) -> str:
        return self.name
