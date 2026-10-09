from __future__ import annotations

from rest_framework import serializers

PATH_MAX = 4096


def path_field(**options: bool) -> serializers.CharField:
    return serializers.CharField(max_length=PATH_MAX, trim_whitespace=False, **options)


class FolderQuerySerializer(serializers.Serializer):
    path = path_field(
        required=False,
        allow_blank=True,
    )


class PathQuerySerializer(serializers.Serializer):
    path = path_field()


class FileUploadSerializer(serializers.Serializer):
    path = path_field()
    file = serializers.FileField(
        allow_empty_file=True,
    )


class FolderCreateSerializer(serializers.Serializer):
    path = path_field()
    name = serializers.CharField(
        max_length=255,
    )
