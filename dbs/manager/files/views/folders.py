from __future__ import annotations

from uuid import UUID

from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.files.serializers import (
    FileEntrySerializer,
    FolderCreateSerializer,
    FolderListingSerializer,
    FolderQuerySerializer,
    PathQuerySerializer,
)
from dbs.manager.files.services import FileService


class FolderView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, application: UUID) -> Response:
        query = FolderQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        folder = FileService(request.user).list(
            application, query.validated_data.get("path")
        )
        entries: list[object] | None = self.paginate_queryset(folder.entries)
        page = self.get_paginated_response(entries).data
        listing = {
            "path": folder.path,
            "parent": folder.parent,
            "root": folder.root,
            "roots": folder.roots,
            **page,
        }
        return Response(FolderListingSerializer(listing).data)

    def delete(self, request: Request, application: UUID) -> Response:
        query = PathQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        FileService(request.user).delete(application, query.validated_data["path"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class FolderCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, application: UUID) -> Response:
        payload = FolderCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        created = FileService(request.user).create_folder(
            application, payload.validated_data["path"], payload.validated_data["name"]
        )
        return Response(
            FileEntrySerializer(created).data, status=status.HTTP_201_CREATED
        )
