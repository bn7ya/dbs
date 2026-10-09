from __future__ import annotations

from rest_framework import serializers

from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.restore_modes import RestoreMode

ACCOUNT_PASSWORD_MAX_LENGTH = 128
SERVER_NAME_MAX_LENGTH = 200


class BackupFileSerializer(serializers.ModelSerializer):
    server = serializers.UUIDField(source="server_id", read_only=True)
    server_name = serializers.CharField(
        source="server.name",
        read_only=True,
    )
    taken_by = serializers.CharField(
        source="created_by.username",
        read_only=True,
        allow_null=True,
    )
    plan = serializers.UUIDField(
        source="plan_id",
        read_only=True,
        allow_null=True,
    )
    plan_name = serializers.CharField(
        source="plan.name",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = BackupFile
        fields = [
            "id",
            "server",
            "server_name",
            "kind",
            "name",
            "size",
            "sha256",
            "validation",
            "validated_at",
            "remote_path",
            "taken_by",
            "plan",
            "plan_name",
            "created_at",
        ]
        read_only_fields = fields


class BackupFilterSerializer(serializers.Serializer):
    server = serializers.UUIDField()


class TakeSerializer(serializers.Serializer):
    server = serializers.UUIDField()


class UploadSerializer(serializers.Serializer):
    server = serializers.UUIDField()
    file = serializers.FileField()


class RestoreSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(
        choices=RestoreMode.choices,
    )
    rehearse = serializers.BooleanField()
    account_password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        max_length=ACCOUNT_PASSWORD_MAX_LENGTH,
    )
    server_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=SERVER_NAME_MAX_LENGTH,
    )
    target_server = serializers.UUIDField(required=False, allow_null=True)
