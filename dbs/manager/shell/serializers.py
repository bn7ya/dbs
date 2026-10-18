from __future__ import annotations

from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail

from dbs.manager.shell.service import APPLICATION, MODES, PLACE_REQUIRED, SERVER

COLS_MIN, COLS_MAX = 20, 500
ROWS_MIN, ROWS_MAX = 5, 200
INPUT_MAX_CHARACTERS = 64 * 1024


class TerminalOpenSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=MODES)
    server = serializers.UUIDField(required=False)
    application = serializers.UUIDField(required=False)
    password = serializers.CharField(
        write_only=True, trim_whitespace=False, max_length=128
    )
    cols = serializers.IntegerField(min_value=COLS_MIN, max_value=COLS_MAX, default=80)
    rows = serializers.IntegerField(min_value=ROWS_MIN, max_value=ROWS_MAX, default=24)

    def validate(self, attrs):
        needed = SERVER if attrs["mode"] == SERVER else APPLICATION
        if attrs.get(needed) is None:
            raise serializers.ValidationError(
                {needed: [ErrorDetail(PLACE_REQUIRED, code="required")]}
            )
        return attrs


class TerminalSerializer(serializers.Serializer):
    id = serializers.CharField(read_only=True)
    mode = serializers.CharField(source="place.mode", read_only=True)
    server = serializers.CharField(source="place.server_id", read_only=True)
    application = serializers.CharField(
        source="place.application_id", read_only=True
    )
    label = serializers.CharField(source="place.label", read_only=True)
    container = serializers.CharField(source="place.container", read_only=True)
    cols = serializers.IntegerField(read_only=True)
    rows = serializers.IntegerField(read_only=True)
    closed = serializers.BooleanField(read_only=True)


class OutputQuerySerializer(serializers.Serializer):
    cursor = serializers.IntegerField(min_value=0, default=0)


class InputSerializer(serializers.Serializer):
    seq = serializers.IntegerField(min_value=0)
    data = serializers.CharField(
        trim_whitespace=False, allow_blank=True, max_length=INPUT_MAX_CHARACTERS
    )


class ResizeSerializer(serializers.Serializer):
    cols = serializers.IntegerField(min_value=COLS_MIN, max_value=COLS_MAX)
    rows = serializers.IntegerField(min_value=ROWS_MIN, max_value=ROWS_MAX)
