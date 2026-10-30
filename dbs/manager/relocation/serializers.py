from __future__ import annotations

from rest_framework import serializers

from dbs.manager.relocation.catalogue import VOLUME
from dbs.manager.servers.serializers import secret_field

APPLICATIONS_MAX = 50
VOLUMES_MAX = 100


class MoveChoiceSerializer(serializers.Serializer):
    application = serializers.UUIDField()
    name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    folder = serializers.CharField(max_length=512, required=False, allow_blank=True)
    skip_volumes = serializers.ListField(
        child=serializers.RegexField(VOLUME.pattern, max_length=255),
        required=False,
        max_length=VOLUMES_MAX,
    )
    copy_plans = serializers.BooleanField(required=False, default=True)


class ServerMoveSerializer(serializers.Serializer):
    target_server = serializers.UUIDField()
    applications = MoveChoiceSerializer(
        many=True, required=False, max_length=APPLICATIONS_MAX
    )
    rehearsal = serializers.BooleanField(required=False, default=True)
    password = secret_field(128)
    confirm_name = serializers.CharField(required=False, allow_blank=True, max_length=200)
    sudo_password = secret_field(256)
    source_sudo_password = secret_field(256)
    resume_of = serializers.IntegerField(required=False, allow_null=True, min_value=1)
