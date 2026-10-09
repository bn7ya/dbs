from __future__ import annotations

from uuid import UUID

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.envfiles.serializers import (
    EnvPasswordSerializer,
    EnvPulledSerializer,
    EnvPullSerializer,
    EnvPushedSerializer,
    EnvRevealedSerializer,
)
from dbs.manager.envfiles.services import EnvFileService


class EnvPullView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        payload = EnvPullSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        pulled = EnvFileService(request.user).pull(payload.validated_data["server"])
        return Response(EnvPulledSerializer(pulled).data)


class EnvRevealView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: UUID) -> Response:
        payload = EnvPasswordSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        content = EnvFileService(request.user).reveal(
            pk, payload.validated_data["password"]
        )
        return Response(
            EnvRevealedSerializer({"content": content}).data,
            headers={"Cache-Control": "no-store"},
        )


class EnvPushView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: UUID) -> Response:
        payload = EnvPasswordSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        pushed = EnvFileService(request.user).push(
            pk, payload.validated_data["password"]
        )
        return Response(EnvPushedSerializer({"version": pushed}).data)
