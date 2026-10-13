from __future__ import annotations

from rest_framework import serializers

from dbs import audit
from dbs.manager.activity import heartbeat
from dbs.models import AuditEvent


class JobConnectionSerializer(serializers.Serializer):
    state = serializers.CharField()
    last_activity_at = serializers.DateTimeField()
    bytes = serializers.IntegerField()


class ActivitySerializer(serializers.ModelSerializer):
    target = serializers.CharField(source="target_name", read_only=True)
    detail = serializers.JSONField(source="data", read_only=True)
    ip = serializers.SerializerMethodField()
    actor = serializers.CharField(
        source="actor.username", read_only=True, allow_null=True
    )
    server = serializers.SerializerMethodField()
    server_name = serializers.SerializerMethodField()
    connection = serializers.SerializerMethodField()

    class Meta:
        model = AuditEvent
        fields = [
            "id",
            "action",
            "status",
            "target",
            "detail",
            "error_code",
            "ip",
            "actor",
            "server",
            "server_name",
            "connection",
            "created_at",
            "started_at",
            "finished_at",
        ]
        read_only_fields = fields

    def _server(self, entry):
        return self.context.get("servers", {}).get(entry.subject)

    def get_ip(self, entry):
        return entry.remote_addr or None

    def get_server(self, entry):
        server = self._server(entry)
        if server is None or server.deleted_at is not None:
            return None
        return str(server.pk)

    def get_server_name(self, entry):
        server = self._server(entry)
        return None if server is None else server.name

    def get_connection(self, entry):
        if entry.status != audit.RUNNING:
            return None
        found = heartbeat.connection_of(entry.pk)
        return None if found is None else JobConnectionSerializer(found).data


class ActivityFilterSerializer(serializers.Serializer):
    server = serializers.UUIDField(required=False)
    action = serializers.CharField(required=False)
    status = serializers.CharField(required=False)


class JobSerializer(serializers.Serializer):
    activity = serializers.IntegerField(source="pk", read_only=True)
