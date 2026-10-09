from __future__ import annotations

from rest_framework import serializers


class EnvFilterSerializer(serializers.Serializer):
    server = serializers.UUIDField()


class EnvCompareQuerySerializer(serializers.Serializer):
    to = serializers.UUIDField()


class EnvPullSerializer(serializers.Serializer):
    server = serializers.UUIDField()


class EnvPasswordSerializer(serializers.Serializer):
    password = serializers.CharField(
        max_length=128, trim_whitespace=False, write_only=True
    )
