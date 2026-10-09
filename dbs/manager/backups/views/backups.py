from __future__ import annotations

from typing import cast
from uuid import UUID

from django.db.models import QuerySet
from django.http import FileResponse
from django.utils.http import content_disposition_header
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.serializers import BackupFileSerializer, BackupFilterSerializer
from dbs.manager.backups.services import BackupService


class BackupListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = BackupFileSerializer

    def get_queryset(self) -> QuerySet[BackupFile]:
        query = BackupFilterSerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        return BackupService(self.request.user).list(query.validated_data["server"])


class BackupDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request: Request, pk: UUID) -> Response:
        BackupService(request.user).delete(pk)
        return Response(status=status.HTTP_204_NO_CONTENT)


class UndoDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: UUID) -> Response:
        backup = BackupService(request.user).undo_delete(pk)
        return Response(BackupFileSerializer(backup).data)


class DownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, pk: UUID) -> FileResponse:
        download = BackupService(request.user).download(pk)
        response = FileResponse(
            download.content, content_type="application/octet-stream"
        )
        response["Content-Length"] = download.size
        response["Content-Disposition"] = cast(
            str, content_disposition_header(as_attachment=True, filename=download.name)
        )
        response["Cache-Control"] = "no-store"
        return response
