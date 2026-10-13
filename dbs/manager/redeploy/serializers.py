from __future__ import annotations

from rest_framework import serializers


def _password() -> serializers.CharField:
    return serializers.CharField(
        required=False,
        allow_blank=True,
        write_only=True,
        trim_whitespace=False,
        max_length=128,
    )


def _confirm_name() -> serializers.CharField:
    return serializers.CharField(required=False, allow_blank=True, max_length=200)


class RedeploySerializer(serializers.Serializer):
    source_server = serializers.UUIDField()
    target_server = serializers.UUIDField()
    backup = serializers.UUIDField(required=False, allow_null=True)
    env_version = serializers.UUIDField(required=False, allow_null=True)
    flush = serializers.BooleanField(required=False, default=False)
    rehearsal = serializers.BooleanField(required=False, default=True)
    password = _password()
    confirm_name = _confirm_name()


class RevertSerializer(serializers.Serializer):
    rehearsal = serializers.BooleanField(required=False, default=True)
    password = _password()
    confirm_name = _confirm_name()
