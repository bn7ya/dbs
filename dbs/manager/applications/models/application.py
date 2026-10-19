from __future__ import annotations

from django.db import models
from django.db.models import Q

from dbs.manager.common.models import BaseModel

DEFAULT_REMOTE_BACKUP_DIR = "/var/backups/dbs"


class Application(BaseModel):
    class Kind(models.TextChoices):
        HOST = "host", "On the server"
        COMPOSE = "compose", "In a Compose service"
        CONTAINER = "container", "In a container"

    class Engine(models.TextChoices):
        NONE = "", "No container"
        DOCKER = "docker", "Docker"
        PODMAN = "podman", "Podman"

    class EnvLocation(models.TextChoices):
        HOST = "host", "On the server"
        CONTAINER = "container", "Inside the container"

    class CheckStatus(models.TextChoices):
        UNKNOWN = "unknown", "Not checked"
        OK = "ok", "Ready"
        PROBLEM = "problem", "Needs attention"
        FAILED = "failed", "Could not connect"

    server = models.ForeignKey(
        "dbs_manager.Server",
        on_delete=models.PROTECT,
        related_name="applications",
    )
    name = models.CharField(max_length=100)

    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.HOST)
    engine = models.CharField(
        max_length=16, choices=Engine.choices, default=Engine.NONE, blank=True
    )
    compose_project = models.CharField(max_length=100, blank=True)
    compose_service = models.CharField(max_length=100, blank=True)
    compose_files = models.JSONField(default=list, blank=True)
    container_name = models.CharField(max_length=255, blank=True)
    project_dir = models.CharField(max_length=512, blank=True)
    workdir = models.CharField(max_length=512, blank=True)
    python_path = models.CharField(max_length=512, default="python3")
    manage_path = models.CharField(max_length=255, default="manage.py")
    settings_module = models.CharField(max_length=200, blank=True)
    remote_backup_dir = models.CharField(
        max_length=512, default=DEFAULT_REMOTE_BACKUP_DIR
    )
    mounts = models.JSONField(default=list, blank=True)
    backup_passphrase_sealed = models.BinaryField(null=True, editable=False)
    file_roots = models.JSONField(default=list, blank=True)
    env_path = models.CharField(max_length=512, blank=True)
    env_location = models.CharField(
        max_length=16, choices=EnvLocation.choices, default=EnvLocation.HOST
    )
    deploy_steps = models.JSONField(default=list, blank=True)

    last_check_status = models.CharField(
        max_length=16,
        choices=CheckStatus.choices,
        default=CheckStatus.UNKNOWN,
    )
    last_check_error = models.CharField(max_length=64, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_check_report = models.JSONField(default=dict, blank=True)
    last_health = models.JSONField(null=True, blank=True)
    timeout_in_container = models.BooleanField(null=True, blank=True)
    discovered_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                condition=Q(deleted_at__isnull=True),
                name="dbs_manager_application_unique_active_name",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def in_container(self) -> bool:
        return self.kind != self.Kind.HOST

    @property
    def env_in_container(self) -> bool:
        return self.in_container and self.env_location == self.EnvLocation.CONTAINER

    @property
    def has_backup_passphrase(self) -> bool:
        return self.backup_passphrase_sealed is not None
