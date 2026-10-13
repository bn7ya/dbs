from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from dbs.manager.permissions import Role


class Account(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="manager_account",
    )
    role = models.CharField(max_length=16, choices=Role.CHOICES, default=Role.VIEWER)
    password_changed_at = models.DateTimeField(default=timezone.now)
    password_change_required = models.BooleanField(default=False)
    totp_secret_sealed = models.BinaryField(null=True, editable=False)
    totp_enrolled_at = models.DateTimeField(null=True, blank=True)
    totp_last_step = models.BigIntegerField(null=True, blank=True)

    class Meta:
        ordering = ("user__username",)
        constraints = [
            models.UniqueConstraint(
                fields=["role"],
                condition=Q(role=Role.MASTER),
                name="dbs_manager_account_one_master",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} ({self.role})"

    @property
    def is_master(self) -> bool:
        return self.role == Role.MASTER

    @property
    def has_two_factor(self) -> bool:
        return self.totp_secret_sealed is not None and self.totp_enrolled_at is not None
