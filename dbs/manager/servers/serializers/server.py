from __future__ import annotations

from django.core.validators import RegexValidator
from rest_framework import serializers

from dbs.manager.servers.models import Server

HOST = RegexValidator(
    r"^(?!-)[A-Za-z0-9._:-]+$",
    message="Enter a host name or an IP address.",
)
PYTHON_MODULE = RegexValidator(
    r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$",
    message="Enter a dotted Python module path, such as config.settings.",
)
PRIVATE_KEY_MAX_LENGTH = 16000
SECRET_MAX_LENGTH = 1024
ACCOUNT_PASSWORD_MAX_LENGTH = 128
HOST_KEY_MAX_LENGTH = 8192
FILE_ROOTS_MAX = 50


def secret_field(max_length: int = SECRET_MAX_LENGTH) -> serializers.CharField:
    return serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        max_length=max_length,
    )


class ServerListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Server
        fields = [
            "id",
            "name",
            "host",
            "port",
            "username",
            "last_check_status",
            "last_checked_at",
        ]
        read_only_fields = fields


class ServerSerializer(serializers.ModelSerializer):
    has_private_key = serializers.BooleanField(read_only=True)
    has_key_passphrase = serializers.BooleanField(read_only=True)
    has_password = serializers.BooleanField(read_only=True)
    host_key_type = serializers.CharField(read_only=True)
    last_check_report = serializers.JSONField(read_only=True)

    class Meta:
        model = Server
        fields = [
            "id",
            "name",
            "host",
            "port",
            "username",
            "auth_method",
            "has_private_key",
            "has_key_passphrase",
            "has_password",
            "host_key",
            "host_key_type",
            "host_key_fingerprint",
            "project_dir",
            "python_path",
            "manage_path",
            "settings_module",
            "remote_backup_dir",
            "file_roots",
            "env_path",
            "last_check_status",
            "last_check_error",
            "last_checked_at",
            "last_check_report",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ServerSettingsSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    host = serializers.CharField(max_length=255, validators=[HOST])
    port = serializers.IntegerField(
        min_value=1,
        max_value=65535,
        required=False,
    )
    username = serializers.CharField(max_length=64)
    auth_method = serializers.ChoiceField(choices=Server.AuthMethod.choices)
    private_key = secret_field(
        PRIVATE_KEY_MAX_LENGTH,
    )
    key_passphrase = secret_field()
    password = secret_field()
    project_dir = serializers.CharField(
        max_length=512,
        allow_blank=True,
        required=False,
    )
    python_path = serializers.CharField(
        max_length=512,
        required=False,
    )
    manage_path = serializers.CharField(
        max_length=255,
        required=False,
    )
    settings_module = serializers.CharField(
        max_length=200,
        allow_blank=True,
        required=False,
        validators=[PYTHON_MODULE],
    )
    remote_backup_dir = serializers.CharField(
        max_length=512,
        required=False,
    )
    backup_passphrase = secret_field()
    file_roots = serializers.ListField(
        child=serializers.CharField(max_length=512),
        max_length=FILE_ROOTS_MAX,
        required=False,
    )
    env_path = serializers.CharField(
        max_length=512,
        allow_blank=True,
        required=False,
    )


class ServerUpdateSerializer(ServerSettingsSerializer):
    account_password = secret_field(
        ACCOUNT_PASSWORD_MAX_LENGTH,
    )


class ServerCreateSerializer(ServerSettingsSerializer):
    host_key = serializers.CharField(max_length=HOST_KEY_MAX_LENGTH)
