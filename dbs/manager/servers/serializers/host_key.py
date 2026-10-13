from __future__ import annotations

from rest_framework import serializers

from dbs.manager.servers.serializers.server import HOST, HOST_KEY_MAX_LENGTH


class FingerprintRequestSerializer(serializers.Serializer):
    host = serializers.CharField(max_length=255, validators=[HOST])
    port = serializers.IntegerField(min_value=1, max_value=65535, default=22)


class HostKeySerializer(serializers.Serializer):
    key_type = serializers.CharField(read_only=True)
    line = serializers.CharField(read_only=True)
    fingerprint = serializers.CharField(read_only=True)


class RepinSerializer(serializers.Serializer):
    host_key = serializers.CharField(max_length=HOST_KEY_MAX_LENGTH)
    password = serializers.CharField(
        max_length=128, trim_whitespace=False, write_only=True
    )


class HostKeyConfirmationSerializer(serializers.Serializer):
    id = serializers.CharField(read_only=True)
    host = serializers.CharField(read_only=True)
    port = serializers.IntegerField(read_only=True)
    key_type = serializers.CharField(read_only=True)
    fingerprint = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    requested_at = serializers.DateTimeField(read_only=True)
    expires_at = serializers.DateTimeField(read_only=True)
