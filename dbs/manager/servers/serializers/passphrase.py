from __future__ import annotations

from rest_framework import serializers


class PasswordSerializer(serializers.Serializer):
    password = serializers.CharField(
        max_length=128, trim_whitespace=False, write_only=True
    )


class PassphraseSerializer(serializers.Serializer):
    passphrase = serializers.CharField(read_only=True)
