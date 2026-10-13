from __future__ import annotations

from rest_framework import serializers

PATH_MAX = 4096
ACCOUNT_PASSWORD_MAX_LENGTH = 128
TICKET_MAX_LENGTH = 64


def path_field(**options: bool) -> serializers.CharField:
    return serializers.CharField(max_length=PATH_MAX, trim_whitespace=False, **options)


class FolderQuerySerializer(serializers.Serializer):
    path = path_field(
        required=False,
        allow_blank=True,
    )


class PathQuerySerializer(serializers.Serializer):
    path = path_field()


class DownloadQuerySerializer(PathQuerySerializer):
    ticket = serializers.CharField(
        required=False, allow_blank=True, max_length=TICKET_MAX_LENGTH
    )


class DownloadRequestSerializer(PathQuerySerializer):
    account_password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        max_length=ACCOUNT_PASSWORD_MAX_LENGTH,
    )


class DownloadLinkSerializer(serializers.Serializer):
    url = serializers.CharField(read_only=True)


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
