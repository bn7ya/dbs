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
    FingerprintRequestSerializer,
    HostKeySerializer,
    RepinSerializer,
    ServerMergeSerializer,
    ServerSerializer,
)
from dbs.manager.servers.services import BrowseService, ServerService


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


class PublicKeyView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, pk: UUID) -> Response:
        return Response({"public_key": ServerService(request.user).public_key(pk)})


class BrowseView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, pk: UUID) -> Response:
        query = BrowseQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        folder = BrowseService(request.user).list(pk, **query.validated_data)
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


class HostKeyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: UUID) -> Response:
        payload = RepinSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        server = ServerService(request.user).repin(pk, **payload.validated_data)
        return Response(ServerSerializer(server).data)


class MergeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: UUID) -> Response:
        payload = ServerMergeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        server = ServerService(request.user).merge(pk, **payload.validated_data)
        return Response(ServerSerializer(server).data)
