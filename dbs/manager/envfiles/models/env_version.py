from __future__ import annotations

from django.db import models

from dbs.manager.common.models import BaseModel


class EnvVersion(BaseModel):
    class Source(models.TextChoices):
        PULLED = "pulled", "Pulled"
        PUSHED = "pushed", "Pushed"
        SCHEDULED = "scheduled", "Scheduled"

    server = models.ForeignKey(
        "dbs_manager.Server",
        on_delete=models.PROTECT,
        related_name="+",
        db_index=False,
    )
    path = models.CharField(max_length=1024)
    content_sealed = models.BinaryField(editable=False)
    fingerprint = models.CharField(max_length=64)
    size = models.PositiveIntegerField()
    key_names = models.JSONField(default=list, blank=True)
    source = models.CharField(max_length=16, choices=Source.choices)

    class Meta(BaseModel.Meta):
        indexes = [
            models.Index(
                fields=["server", "-created_at"], name="dbs_manager_env_server_idx"
            ),
        ]

    def __str__(self) -> str:
        taken = f" {self.created_at:%Y-%m-%d %H:%M}" if self.created_at else ""
        return f"{self.path}, {self.source}{taken}"
