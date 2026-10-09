from __future__ import annotations

import stat
from typing import TYPE_CHECKING

from rest_framework import serializers

if TYPE_CHECKING:
    from dbs.manager.servers.gateways import RemoteEntry

ENTRY_KINDS = ["file", "folder", "link", "other"]


class FileEntrySerializer(serializers.Serializer):
    name = serializers.CharField(
        read_only=True,
    )
    path = serializers.CharField(
        read_only=True,
    )
    kind = serializers.ChoiceField(
        choices=ENTRY_KINDS,
        read_only=True,
    )
    size = serializers.IntegerField(
        read_only=True,
        allow_null=True,
    )
    modified = serializers.DateTimeField(
        source="mtime",
        read_only=True,
        allow_null=True,
    )
    mode = serializers.SerializerMethodField()

    def get_mode(self, entry: RemoteEntry) -> str | None:
        return (
            None if entry.permissions is None else stat.filemode(entry.permissions)[1:]
        )


class FolderListingSerializer(serializers.Serializer):
    path = serializers.CharField(
        read_only=True,
    )
    parent = serializers.CharField(
        read_only=True,
        allow_null=True,
    )
    root = serializers.CharField(
        read_only=True,
    )
    roots = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )
    count = serializers.IntegerField(
        read_only=True,
    )
    next = serializers.URLField(read_only=True, allow_null=True)
    previous = serializers.URLField(read_only=True, allow_null=True)
    results = FileEntrySerializer(
        many=True,
        read_only=True,
    )
