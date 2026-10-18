from __future__ import annotations

from django.core.validators import RegexValidator
from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail

from dbs.manager.servers.models import Server

HOST = RegexValidator(
    r"^(?!-)[A-Za-z0-9._:-]+$",
    message="Enter a host name or an IP address.",
)
PRIVATE_KEY_MAX_LENGTH = 16000
SECRET_MAX_LENGTH = 1024
ACCOUNT_PASSWORD_MAX_LENGTH = 128
HOST_KEY_MAX_LENGTH = 8192
REQUIRED = "This field is required."


def secret_field(max_length: int = SECRET_MAX_LENGTH) -> serializers.CharField:
    return serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        max_length=max_length,
    )


class ServerListSerializer(serializers.ModelSerializer):
    application_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Server
        fields = [
            "id",
            "name",
            "host",
            "port",
            "username",
            "host_key_fingerprint",
            "engines",
            "application_count",
            "last_check_status",
            "last_checked_at",
            "connection_state",
            "last_seen_at",
            "last_connection_error",
        ]
        read_only_fields = fields


class ServerSerializer(serializers.ModelSerializer):
    application_count = serializers.SerializerMethodField()
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
            "engines",
            "application_count",
            "last_check_status",
            "last_check_error",
            "last_checked_at",
            "last_check_report",
            "timeout_on_host",
            "connection_state",
            "last_seen_at",
            "last_connection_error",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_application_count(self, server: Server) -> int:
        return server.applications.filter(deleted_at__isnull=True).count()


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
    private_key = secret_field(PRIVATE_KEY_MAX_LENGTH)
    key_passphrase = secret_field()
    password = secret_field()


class AccountPasswordSerializer(serializers.Serializer):
    account_password = secret_field(ACCOUNT_PASSWORD_MAX_LENGTH)


class ServerUpdateSerializer(ServerSettingsSerializer):
    account_password = secret_field(ACCOUNT_PASSWORD_MAX_LENGTH)


class ServerCreateSerializer(ServerSettingsSerializer):
    generate_key = serializers.BooleanField(required=False, default=False)
    host_key = serializers.CharField(max_length=HOST_KEY_MAX_LENGTH)
    auth_method = serializers.ChoiceField(
        choices=Server.AuthMethod.choices, required=False
    )

    def validate(self, attrs):
        if attrs.get("generate_key"):
            attrs["auth_method"] = Server.AuthMethod.KEY
        elif "auth_method" not in attrs:
            raise serializers.ValidationError(
                {"auth_method": [ErrorDetail(REQUIRED, code="required")]}
            )
        return attrs


class ServerMergeSerializer(serializers.Serializer):
    into = serializers.UUIDField()
    account_password = secret_field(ACCOUNT_PASSWORD_MAX_LENGTH)


class AddedServerSerializer(serializers.BaseSerializer):
    def to_representation(self, instance):
        body = dict(ServerSerializer(instance.server).data)
        if instance.public_key:
            body["public_key"] = instance.public_key
            body["authorized_keys_hint"] = instance.authorized_keys_hint
        return body
