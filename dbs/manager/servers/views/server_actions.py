from __future__ import annotations

from uuid import UUID

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.servers.serializers import (
    FingerprintRequestSerializer,
    HostKeySerializer,
    PassphraseSerializer,
    PasswordSerializer,
    RepinSerializer,
    ServerSerializer,
)
from dbs.manager.servers.services import ServerService


class FingerprintView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        payload = FingerprintRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        key = ServerService(request.user).fingerprint(**payload.validated_data)
        return Response(HostKeySerializer(key).data)


class CheckView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: UUID) -> Response:
        server = ServerService(request.user).check(pk)
        return Response(ServerSerializer(server).data)


class HostKeyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: UUID) -> Response:
        payload = RepinSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        server = ServerService(request.user).repin(pk, **payload.validated_data)
        return Response(ServerSerializer(server).data)


class PassphraseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: UUID) -> Response:
        payload = PasswordSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        passphrase = ServerService(request.user).reveal_passphrase(
            pk, **payload.validated_data
        )
        return Response(
            PassphraseSerializer({"passphrase": passphrase}).data,
            headers={"Cache-Control": "no-store"},
        )
