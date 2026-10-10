from __future__ import annotations

from uuid import UUID

from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.servers.serializers import (
    BrowseListingSerializer,
    BrowseQuerySerializer,
    DiscoverRequestSerializer,
    FingerprintRequestSerializer,
    HostKeySerializer,
    PassphraseSerializer,
    PasswordSerializer,
    RepinSerializer,
    ServerSerializer,
)
from dbs.manager.servers.services import (
    BrowseService,
    DiscoveryService,
    ServerService,
)


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
        service = ServerService(request.user)
        server = service.check(pk)
        return Response(
            {**ServerSerializer(server).data, **service.compatibility(server)}
        )


class PublicKeyView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, pk: UUID) -> Response:
        return Response({"public_key": ServerService(request.user).public_key(pk)})


class DiscoverView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: UUID) -> Response:
        payload = DiscoverRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        project_dir = payload.validated_data.get("project_dir") or None
        account_password = payload.validated_data.get("account_password", "")
        return Response(
            DiscoveryService(request.user).discover(pk, project_dir, account_password)
        )


class BrowseView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, pk: UUID) -> Response:
        query = BrowseQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        folder = BrowseService(request.user).list(
            pk, query.validated_data.get("path") or None
        )
        entries: list[object] | None = self.paginate_queryset(folder.entries)
        page = self.get_paginated_response(entries).data
        listing = {
            "path": folder.path,
            "parent": folder.parent,
            "home": folder.home,
            "project": folder.project,
            "truncated": folder.truncated,
            **page,
        }
        return Response(BrowseListingSerializer(listing).data)


class PassphraseCaptureView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: UUID) -> Response:
        ServerService(request.user).capture_passphrase(pk)
        return Response({"captured": True})


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
