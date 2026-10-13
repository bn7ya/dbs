from __future__ import annotations

from django.db import models


class RecoveryCode(models.Model):
    account = models.ForeignKey(
        "dbs_manager.Account", on_delete=models.CASCADE, related_name="recovery_codes"
    )
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("created_at", "id")
        indexes = [
            models.Index(fields=["account", "digest"], name="dbs_manager_recovery_idx"),
        ]

    def __str__(self) -> str:
        return f"recovery code of {self.account_id}"
