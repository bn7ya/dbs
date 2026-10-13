from __future__ import annotations

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from dbs.manager.common.models import BaseModel

DEFAULT_REMOTE_BACKUP_DIR = "/var/backups/dbs"


class Server(BaseModel):
    class AuthMethod(models.TextChoices):
        KEY = "key", "Private key"
        PASSWORD = "password", "Password"

    class Runtime(models.TextChoices):
        HOST = "host", "On the server"
        COMPOSE = "compose", "In a Docker Compose service"

    class CheckStatus(models.TextChoices):
        UNKNOWN = "unknown", "Not checked"
        OK = "ok", "Ready"
        PROBLEM = "problem", "Needs attention"
        FAILED = "failed", "Could not connect"

    class ConnectionState(models.TextChoices):
        UNKNOWN = "unknown", "Not seen yet"
        ONLINE = "online", "Online"
        OFFLINE = "offline", "Offline"

    name = models.CharField(max_length=100)
    host = models.CharField(max_length=255)
    port = models.PositiveIntegerField(
        default=22,
        validators=[MinValueValidator(1), MaxValueValidator(65535)],
    )
    username = models.CharField(max_length=64)

    auth_method = models.CharField(max_length=16, choices=AuthMethod.choices)
    private_key_sealed = models.BinaryField(null=True, editable=False)
    key_passphrase_sealed = models.BinaryField(null=True, editable=False)
    password_sealed = models.BinaryField(null=True, editable=False)

    host_key = models.TextField()
    host_key_fingerprint = models.CharField(max_length=100)

    runtime = models.CharField(
        max_length=16, choices=Runtime.choices, default=Runtime.HOST
    )
    compose_service = models.CharField(max_length=100, blank=True)
    compose_files = models.JSONField(default=list, blank=True)
    project_dir = models.CharField(max_length=512, blank=True)
    python_path = models.CharField(max_length=512, default="python3")
    manage_path = models.CharField(max_length=255, default="manage.py")
    settings_module = models.CharField(max_length=200, blank=True)
    remote_backup_dir = models.CharField(
        max_length=512, default=DEFAULT_REMOTE_BACKUP_DIR
    )
    backup_passphrase_sealed = models.BinaryField(null=True, editable=False)
    file_roots = models.JSONField(default=list, blank=True)
    env_path = models.CharField(max_length=512, blank=True)

    last_check_status = models.CharField(
        max_length=16,
        choices=CheckStatus.choices,
        default=CheckStatus.UNKNOWN,
    )
    last_check_error = models.CharField(max_length=64, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_check_report = models.JSONField(default=dict, blank=True)
    last_health = models.JSONField(null=True, blank=True)
    timeout_on_host = models.BooleanField(null=True, blank=True)
    timeout_in_container = models.BooleanField(null=True, blank=True)

    connection_state = models.CharField(
        max_length=16,
        choices=ConnectionState.choices,
        default=ConnectionState.UNKNOWN,
    )
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_connection_error = models.CharField(max_length=64, blank=True)

    class Meta(BaseModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                condition=Q(deleted_at__isnull=True),
                name="dbs_manager_server_unique_active_name",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def in_compose(self) -> bool:
        return self.runtime == self.Runtime.COMPOSE

    @property
    def host_key_type(self) -> str:
        return self.host_key.split(" ", 1)[0]

    @property
    def has_private_key(self) -> bool:
        return self.private_key_sealed is not None

    @property
    def has_key_passphrase(self) -> bool:
        return self.key_passphrase_sealed is not None

    @property
    def has_password(self) -> bool:
        return self.password_sealed is not None

    @property
    def has_backup_passphrase(self) -> bool:
        return self.backup_passphrase_sealed is not None
