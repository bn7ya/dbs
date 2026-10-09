from __future__ import annotations

from rest_framework import serializers

from dbs.manager.backups.models import (
    PLAN_KEEP_MAX,
    PLAN_PATH_MAX_LENGTH,
    PLAN_PATHS_MAX,
    BackupPlan,
)

ACCOUNT_PASSWORD_MAX_LENGTH = 128


class BackupPlanSerializer(serializers.ModelSerializer):
    server = serializers.UUIDField(source="server_id", read_only=True)

    class Meta:
        model = BackupPlan
        fields = [
            "id",
            "server",
            "name",
            "kind",
            "paths",
            "pattern",
            "interval_minutes",
            "keep",
            "keep_remote",
            "enabled",
            "next_run_at",
            "last_run_at",
            "last_status",
            "last_error_code",
            "created_at",
        ]
        read_only_fields = fields


class PlanUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    paths = serializers.ListField(
        child=serializers.CharField(max_length=PLAN_PATH_MAX_LENGTH, allow_blank=True),
        max_length=PLAN_PATHS_MAX,
        required=False,
    )
    pattern = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    interval_minutes = serializers.IntegerField(
        allow_null=True,
        required=False,
    )
    keep = serializers.IntegerField(
        min_value=1,
        max_value=PLAN_KEEP_MAX,
        required=False,
    )
    keep_remote = serializers.IntegerField(
        min_value=0,
        max_value=PLAN_KEEP_MAX,
        required=False,
    )
    enabled = serializers.BooleanField(
        required=False,
    )
    account_password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        max_length=ACCOUNT_PASSWORD_MAX_LENGTH,
    )


class PlanCreateSerializer(PlanUpdateSerializer):
    server = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=BackupPlan.Kind.choices)
