from __future__ import annotations

from rest_framework import serializers

from dbs.manager.console.service import LINE_MAX


class ConsoleRequestSerializer(serializers.Serializer):
    line = serializers.CharField(max_length=LINE_MAX, trim_whitespace=False)
    password = serializers.CharField(
        required=False,
        allow_blank=True,
        write_only=True,
        trim_whitespace=False,
        max_length=128,
    )


class ConsoleResultSerializer(serializers.Serializer):
    exit_code = serializers.IntegerField()
    output = serializers.CharField()
    activities = serializers.ListField(child=serializers.IntegerField())
    password_required = serializers.BooleanField()
    error_code = serializers.CharField()
