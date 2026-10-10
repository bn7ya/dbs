from __future__ import annotations

from rest_framework import serializers


class RedeploySerializer(serializers.Serializer):
    source_server = serializers.UUIDField()
    target_server = serializers.UUIDField()
    backup = serializers.UUIDField()
    env_version = serializers.UUIDField(required=False, allow_null=True)
    archives = serializers.ListField(
        child=serializers.UUIDField(), required=False, max_length=50
    )
    migrate = serializers.BooleanField(required=False, default=False)
    flush = serializers.BooleanField(required=False, default=False)
    rehearsal = serializers.BooleanField(required=False, default=True)
    password = serializers.CharField(
        required=False,
        allow_blank=True,
        write_only=True,
        trim_whitespace=False,
        max_length=128,
    )
    confirm_name = serializers.CharField(
        required=False, allow_blank=True, max_length=200
    )
