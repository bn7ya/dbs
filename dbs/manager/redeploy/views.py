from __future__ import annotations

from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.activity.serializers import JobSerializer
from dbs.manager.redeploy.services import RedeployService


class RedeploySerializer(serializers.Serializer):
    source_server = serializers.UUIDField()
    target_server = serializers.UUIDField()
    backup = serializers.UUIDField()
    env_version = serializers.UUIDField(required=False, allow_null=True)
    archives = serializers.ListField(
        child=serializers.UUIDField(), required=False, max_length=50
    )
    migrate = serializers.BooleanField(required=False, default=False)
    flush = serializers.BooleanField(required=False, default=False)
    rehearsal = serializers.BooleanField(required=False, default=True)
    password = serializers.CharField(
        required=False,
        allow_blank=True,
        write_only=True,
        trim_whitespace=False,
        max_length=128,
    )
    confirm_name = serializers.CharField(
        required=False, allow_blank=True, max_length=200
    )


class RedeployView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        payload = RedeploySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        data["archives"] = list(dict.fromkeys(data.get("archives", [])))
        job = RedeployService(request.user).start(**data)
        return Response(JobSerializer(job).data, status=status.HTTP_202_ACCEPTED)
