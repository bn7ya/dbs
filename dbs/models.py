from __future__ import annotations

import os

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .crypto.secrets import encrypt_secret, is_encrypted, looks_sealed
from .naming import DEFAULT_PREFIX
from .retention import MAXIMUM_KEEP

SECRET_PLACEHOLDER = "<unreadable>"


class SecretField(models.TextField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("blank", True)
        kwargs.setdefault("default", "")
        super().__init__(*args, **kwargs)

    def get_prep_value(self, value):
        if not value:
            return ""
        if is_encrypted(value) and looks_sealed(value):
            return value
        return encrypt_secret(str(value))


class SecurityLevel(models.TextChoices):
    RELAXED = "relaxed", "Relaxed"
    BALANCED = "balanced", "Balanced"
    STRICT = "strict", "Strict"
    PARANOID = "paranoid", "Paranoid"


LEVEL_PRESETS = {
    SecurityLevel.RELAXED: {
        "warn_threshold": 0.75,
        "logout_threshold": 0.95,
        "learning_logins": 20,
        "idle_timeout_minutes": 480,
    },
    SecurityLevel.BALANCED: {
        "warn_threshold": 0.60,
        "logout_threshold": 0.85,
        "learning_logins": 10,
        "idle_timeout_minutes": 120,
    },
    SecurityLevel.STRICT: {
        "warn_threshold": 0.50,
        "logout_threshold": 0.72,
        "learning_logins": 5,
        "idle_timeout_minutes": 30,
    },
    SecurityLevel.PARANOID: {
        "warn_threshold": 0.40,
        "logout_threshold": 0.60,
        "learning_logins": 0,
        "idle_timeout_minutes": 15,
    },
}


class BackupRecord(models.Model):
    filename = models.CharField(max_length=255)
    size_bytes = models.BigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, default="")
    location = models.CharField(max_length=1024, blank=True, default="")
    prefix = models.CharField(max_length=64, default=DEFAULT_PREFIX)
    database = models.CharField(max_length=64, default="default")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "backup"
        verbose_name_plural = "backups"

    def __str__(self):
        return self.filename

    @property
    def stored_locally(self):
        return bool(self.location)

    def local_path(self):
        from .conf import setting

        directory = setting("DBS_BACKUP_DIR", None)
        if not self.stored_locally or not directory:
            return None
        root = os.path.realpath(os.path.expanduser(str(directory)))
        candidate = os.path.realpath(os.path.join(root, os.path.basename(self.location)))
        if os.path.commonpath([root, candidate]) != root:
            return None
        return candidate if os.path.isfile(candidate) else None


class AuditStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"


class AuditEvent(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    action = models.CharField(max_length=64)
    target_name = models.CharField(max_length=1024, blank=True, default="")
    detail = models.TextField(blank=True, default="")
    data = models.JSONField(blank=True, default=dict)
    status = models.CharField(
        max_length=16, choices=AuditStatus.choices, default=AuditStatus.SUCCEEDED
    )
    error_code = models.CharField(max_length=64, blank=True, default="")
    subject = models.CharField(max_length=64, blank=True, default="")
    remote_addr = models.CharField(max_length=64, blank=True, default="")
    succeeded = models.BooleanField(default=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    chain_index = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    chain_hash = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
            models.Index(fields=["subject", "-created_at"]),
        ]

    def __str__(self):
        if self.actor_name:
            return f"{self.action} by {self.actor_name}"
        return self.action

    @property
    def actor_name(self):
        if self.actor_id is not None and self.actor is not None:
            return self.actor.get_username()
        return (self.data or {}).get("actor_username", "")

    @property
    def duration(self):
        if self.started_at is None or self.finished_at is None:
            return None
        return self.finished_at - self.started_at


class Lease(models.Model):
    name = models.CharField(max_length=64, unique=True)
    owner = models.CharField(max_length=128, blank=True, default="")
    expires_at = models.DateTimeField()
    renewed_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} held by {self.owner or 'nobody'}"


class BackupSchedule(models.Model):
    enabled = models.BooleanField(default=False)
    interval = models.CharField(max_length=16, default="24h")
    keep = models.PositiveIntegerField(
        default=MAXIMUM_KEEP,
        validators=[MinValueValidator(1), MaxValueValidator(MAXIMUM_KEEP)],
    )
    database = models.CharField(max_length=64, default="default")
    next_run_at = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=16, blank=True, default="")
    last_error = models.TextField(blank=True, default="")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "backup schedule"
        verbose_name_plural = "backup schedule"

    def __str__(self):
        if not self.enabled:
            return "Scheduled backups are off"
        return f"Every {self.interval}, keeping {self.keep}"

    @classmethod
    def load(cls):
        from .conf import setting

        schedule = cls.objects.order_by("pk").first()
        if schedule is not None:
            return schedule
        schedule, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "interval": str(setting("DBS_SCHEDULE_INTERVAL", "24h")),
                "keep": cls.seed_keep(setting("DBS_SCHEDULE_KEEP", MAXIMUM_KEEP)),
            },
        )
        return schedule

    @staticmethod
    def seed_keep(value):
        try:
            keep = int(value)
        except (TypeError, ValueError):
            return MAXIMUM_KEEP
        return min(max(keep, 1), MAXIMUM_KEEP)

    @property
    def interval_seconds(self):
        from .scheduling import parse_interval

        return parse_interval(self.interval)


class SecurityPolicy(models.Model):
    configured = models.BooleanField(default=False)
    level = models.CharField(
        max_length=16, choices=SecurityLevel.choices, default=SecurityLevel.BALANCED
    )
    expected_networks = models.TextField(blank=True, default="")
    trusted_networks = models.TextField(blank=True, default="")
    warn_threshold = models.FloatField(default=0.60)
    logout_threshold = models.FloatField(default=0.85)
    learning_logins = models.PositiveIntegerField(default=10)
    idle_timeout_minutes = models.PositiveIntegerField(default=120)
    collect_location = models.BooleanField(default=False)
    notify_emails = models.TextField(blank=True, default="")
    configured_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "security policy"
        verbose_name_plural = "security policy"

    def __str__(self):
        return f"DBS security policy ({self.get_level_display()})"

    @classmethod
    def load(cls):
        policy = cls.objects.order_by("pk").first()
        if policy is None:
            policy = cls.objects.create()
        return policy

    def apply_level(self, level):
        self.level = level
        for field, value in LEVEL_PRESETS[SecurityLevel(level)].items():
            setattr(self, field, value)


class KnownLocation(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dbs_locations"
    )
    label = models.CharField(max_length=64, default="usual")
    latitude = models.FloatField()
    longitude = models.FloatField()
    radius_km = models.FloatField(default=50.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("user_id", "label")

    def __str__(self):
        return f"{self.label} ({self.latitude}, {self.longitude})"


class SessionEvent(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dbs_events"
    )
    session_key_hash = models.CharField(max_length=64, blank=True, default="")
    kind = models.CharField(max_length=32, default="request")
    remote_addr = models.CharField(max_length=64, blank=True, default="")
    ip_prefix = models.CharField(max_length=64, blank=True, default="")
    ua_hash = models.CharField(max_length=64, blank=True, default="")
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    accuracy_m = models.FloatField(null=True, blank=True)
    features = models.JSONField(default=dict)
    score = models.FloatField(default=0.0)
    verdict = models.CharField(max_length=16, default="ok")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["user", "-created_at"])]


class AnomalyEvent(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dbs_anomalies"
    )
    score = models.FloatField(default=0.0)
    reasons = models.JSONField(default=list)
    action_taken = models.CharField(max_length=16, default="warn")
    remote_addr = models.CharField(max_length=64, blank=True, default="")
    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["user", "-created_at"])]

    def __str__(self):
        return f"{self.action_taken} at {self.created_at:%Y-%m-%d %H:%M}"


class Lockout(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dbs_lockout"
    )
    reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"lockout for {self.user_id}"


class Panel(SecurityPolicy):
    class Meta:
        proxy = True
        verbose_name = "DBS panel"
        verbose_name_plural = "DBS panel"
