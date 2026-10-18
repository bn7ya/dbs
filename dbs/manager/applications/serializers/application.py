from __future__ import annotations

from django.core.validators import RegexValidator
from rest_framework import serializers

from dbs.manager.applications.models import Application
from dbs.manager.servers.serializers import (
    absolute_or_blank,
    optional_path,
    secret_field,
)

PYTHON_MODULE = RegexValidator(
    r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$",
    message="Enter a dotted Python module path, such as config.settings.",
)
COMPOSE_NAME = RegexValidator(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
    message="Enter the name the compose file gives it, such as backend.",
)
CONTAINER_NAME = RegexValidator(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$",
    message="Enter the container's name or id.",
)
COMPOSE_FILE = RegexValidator(
    r"^(?!-)(?!(.*/)?\.\.(/|$))[^\x00\r\n]+$",
    message="Enter a compose file path without '..' in it, such as compose.prod.yaml.",
)
COMPOSE_FILES_MAX = 10
FILE_ROOTS_MAX = 50
MOUNTS_MAX = 100
ACCOUNT_PASSWORD_MAX_LENGTH = 128


class ServerSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    host = serializers.CharField(read_only=True)
    port = serializers.IntegerField(read_only=True)
    connection_state = serializers.CharField(read_only=True)


class ApplicationListSerializer(serializers.ModelSerializer):
    server = ServerSummarySerializer(read_only=True)

    class Meta:
        model = Application
        fields = [
            "id",
            "name",
            "server",
            "kind",
            "engine",
            "compose_service",
            "container_name",
            "project_dir",
            "last_check_status",
            "last_checked_at",
        ]
        read_only_fields = fields


class ApplicationSerializer(serializers.ModelSerializer):
    server = ServerSummarySerializer(read_only=True)
    has_backup_passphrase = serializers.BooleanField(read_only=True)
    last_check_report = serializers.JSONField(read_only=True)

    class Meta:
        model = Application
        fields = [
            "id",
            "name",
            "server",
            "kind",
            "engine",
            "compose_project",
            "compose_service",
            "compose_files",
            "container_name",
            "project_dir",
            "workdir",
            "python_path",
            "manage_path",
            "settings_module",
            "remote_backup_dir",
            "mounts",
            "file_roots",
            "env_path",
            "env_location",
            "has_backup_passphrase",
            "last_check_status",
            "last_check_error",
            "last_checked_at",
            "last_check_report",
            "last_health",
            "timeout_in_container",
            "discovered_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class MountSerializer(serializers.Serializer):
    type = serializers.CharField(max_length=32, required=False, allow_blank=True)
    source = serializers.CharField(max_length=4096)
    destination = serializers.CharField(max_length=4096)
    rw = serializers.BooleanField(required=False, default=True)

    def validate_source(self, value: str) -> str:
        return absolute_or_blank(value)

    def validate_destination(self, value: str) -> str:
        return absolute_or_blank(value)


class ApplicationSettingsSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    kind = serializers.ChoiceField(choices=Application.Kind.choices, required=False)
    engine = serializers.ChoiceField(
        choices=Application.Engine.choices, required=False, allow_blank=True
    )
    compose_project = serializers.CharField(
        max_length=100, allow_blank=True, required=False, validators=[COMPOSE_NAME]
    )
    compose_service = serializers.CharField(
        max_length=100, allow_blank=True, required=False, validators=[COMPOSE_NAME]
    )
    compose_files = serializers.ListField(
        child=serializers.CharField(max_length=512, validators=[COMPOSE_FILE]),
        max_length=COMPOSE_FILES_MAX,
        required=False,
    )
    container_name = serializers.CharField(
        max_length=128, allow_blank=True, required=False, validators=[CONTAINER_NAME]
    )
    project_dir = serializers.CharField(max_length=512, allow_blank=True, required=False)
    workdir = serializers.CharField(max_length=512, allow_blank=True, required=False)
    python_path = serializers.CharField(max_length=512, required=False)
    manage_path = serializers.CharField(max_length=255, required=False)
    settings_module = serializers.CharField(
        max_length=200, allow_blank=True, required=False, validators=[PYTHON_MODULE]
    )
    remote_backup_dir = serializers.CharField(max_length=512, required=False)
    mounts = MountSerializer(many=True, required=False, max_length=MOUNTS_MAX)
    backup_passphrase = secret_field()
    file_roots = serializers.ListField(
        child=serializers.CharField(max_length=512),
        max_length=FILE_ROOTS_MAX,
        required=False,
    )
    env_path = serializers.CharField(max_length=512, allow_blank=True, required=False)
    env_location = serializers.ChoiceField(
        choices=Application.EnvLocation.choices, required=False
    )
    discovered = serializers.BooleanField(required=False, default=False)


class ApplicationCreateSerializer(ApplicationSettingsSerializer):
    server = serializers.UUIDField()


class ApplicationUpdateSerializer(ApplicationSettingsSerializer):
    account_password = secret_field(ACCOUNT_PASSWORD_MAX_LENGTH)


class ApplicationFilterSerializer(serializers.Serializer):
    search = serializers.CharField(max_length=100, required=False, allow_blank=True)
    server = serializers.UUIDField(required=False)


class DiscoverRequestSerializer(serializers.Serializer):
    server = serializers.UUIDField()
    folder = optional_path()
    account_password = secret_field(ACCOUNT_PASSWORD_MAX_LENGTH)

    def validate_folder(self, value: str) -> str:
        return absolute_or_blank(value)


class CheckedApplicationSerializer(serializers.BaseSerializer):
    def to_representation(self, instance):
        return {
            **ApplicationSerializer(instance.application).data,
            **instance.compatibility,
        }
