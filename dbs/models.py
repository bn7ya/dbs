from __future__ import annotations

import os

from django.conf import settings
from django.db import models

from .crypto.secrets import encrypt_secret, is_encrypted, looks_sealed, read_secret
from .exceptions import InvalidPassphrase
from .naming import DEFAULT_PREFIX

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


class AuthMethod(models.TextChoices):
    AGENT = "agent", "SSH agent"
    KEY_FILE = "key_file", "Private key file on the server"
    KEY_MATERIAL = "key_material", "Private key pasted here"
    PASSWORD = "password", "Password"


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


class BackupTarget(models.Model):
    name = models.SlugField(max_length=64, unique=True)
    host = models.CharField(max_length=255)
    port = models.PositiveIntegerField(default=22)
    username = models.CharField(max_length=128)
    remote_dir = models.CharField(max_length=512, default=".")
    auth_method = models.CharField(
        max_length=16, choices=AuthMethod.choices, default=AuthMethod.AGENT
    )
    key_filename = models.CharField(max_length=512, blank=True, default="")
    known_hosts = models.CharField(max_length=512, blank=True, default="")
    auto_add_host_key = models.BooleanField(default=False)
    connect_timeout = models.FloatField(default=30.0)
    is_default = models.BooleanField(default=False)
    notes = models.TextField(blank=True, default="")
    secret_password = SecretField()
    secret_key_material = SecretField()
    secret_key_passphrase = SecretField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "SFTP target"
        verbose_name_plural = "SFTP targets"

    def __str__(self):
        return f"{self.name} ({self.username}@{self.host}:{self.port})"

    def secret(self, field):
        try:
            return read_secret(getattr(self, field))
        except InvalidPassphrase:
            return None

    def has_unreadable_secret(self):
        fields = ("secret_password", "secret_key_material", "secret_key_passphrase")
        return any(getattr(self, name) and self.secret(name) is None for name in fields)

    def ssh_target(self):
        from .transports.ssh import SSHTarget

        data = {
            "host": self.host,
            "username": self.username,
            "port": self.port,
            "remote_dir": self.remote_dir,
            "auto_add_host_key": self.auto_add_host_key,
            "connect_timeout": self.connect_timeout,
            "use_agent": self.auth_method == AuthMethod.AGENT,
        }
        if self.known_hosts:
            data["known_hosts"] = self.known_hosts
        if self.auth_method == AuthMethod.KEY_FILE and self.key_filename:
            data["key_filename"] = self.key_filename
        if self.auth_method == AuthMethod.KEY_MATERIAL:
            data["private_key"] = self.secret("secret_key_material")
        if self.auth_method == AuthMethod.PASSWORD:
            data["password"] = self.secret("secret_password")
        passphrase = self.secret("secret_key_passphrase")
        if passphrase:
            data["key_passphrase"] = passphrase
        return SSHTarget.from_dict({k: v for k, v in data.items() if v is not None})


class BackupRecord(models.Model):
    filename = models.CharField(max_length=255)
    size_bytes = models.BigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, default="")
    target = models.ForeignKey(
        BackupTarget, null=True, blank=True, on_delete=models.SET_NULL
    )
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
        return self.target_id is None and bool(self.location)

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

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
            models.Index(fields=["subject", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.action} by {self.actor_id or 'system'}"

    @property
    def duration(self):
        if self.started_at is None or self.finished_at is None:
            return None
        return self.finished_at - self.started_at


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
