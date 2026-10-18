from __future__ import annotations

from typing import cast
from urllib.parse import urlencode
from uuid import UUID

from django.http import HttpRequest, StreamingHttpResponse
from django.urls import reverse
from django.utils.http import content_disposition_header
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.files.serializers import (
    DownloadLinkSerializer,
    DownloadQuerySerializer,
    DownloadRequestSerializer,
    FileEntrySerializer,
    FileUploadSerializer,
)
from dbs.manager.files.services import FileService
from dbs.manager.files.uploads import UploadHandler


class DownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, application: UUID) -> StreamingHttpResponse:
        query = DownloadQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        download = FileService(request.user).download(application, **query.validated_data)
        response = StreamingHttpResponse(
            download.content, content_type="application/octet-stream"
        )
        if download.size is not None:
            response["Content-Length"] = download.size
        response["Content-Disposition"] = cast(
            str, content_disposition_header(as_attachment=True, filename=download.name)
        )
        response["Cache-Control"] = "no-store"
        return response

    def post(self, request: Request, application: UUID) -> Response:
        payload = DownloadRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        ticket = FileService(request.user).download_ticket(
            application, **payload.validated_data
        )
        query = {"path": payload.validated_data["path"]}
        if ticket:
            query["ticket"] = ticket
        url = f"{reverse('files:download', args=[application])}?{urlencode(query)}"
        return Response(
            DownloadLinkSerializer({"url": url}).data,
            headers={"Cache-Control": "no-store"},
        )


class UploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    def initialize_request(
        self, request: HttpRequest, *args: object, **kwargs: object
    ) -> Request:
        request.upload_handlers = [UploadHandler(request)]
        return super().initialize_request(request, *args, **kwargs)

    def post(self, request: Request, application: UUID) -> Response:
        payload = FileUploadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        created = FileService(request.user).upload(
            application, payload.validated_data["path"], payload.validated_data["file"]
        )
        return Response(
            FileEntrySerializer(created).data, status=status.HTTP_201_CREATED
        )
