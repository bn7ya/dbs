from __future__ import annotations

from django.http import HttpRequest
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.backups.serializers import BackupFileSerializer, UploadSerializer
from dbs.manager.backups.services import BackupService
from dbs.manager.backups.uploads import UploadHandler


class UploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    def initialize_request(
        self, request: HttpRequest, *args: object, **kwargs: object
    ) -> Request:
        request.upload_handlers = [UploadHandler(request)]
        return super().initialize_request(request, *args, **kwargs)

    def post(self, request: Request) -> Response:
        payload = UploadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        backup = BackupService(request.user).upload(
            payload.validated_data["server"], payload.validated_data["file"]
        )
        return Response(
            BackupFileSerializer(backup).data, status=status.HTTP_201_CREATED
        )
