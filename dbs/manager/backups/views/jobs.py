from __future__ import annotations

from uuid import UUID

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.activity.serializers import JobSerializer
from dbs.manager.backups.serializers import (
    RestoreSerializer,
    TakeSerializer,
)
from dbs.manager.backups.services import BackupService


class TakeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        payload = TakeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        job = BackupService(request.user).take(payload.validated_data["server"])
        return Response(JobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


class VerifyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: UUID) -> Response:
        job = BackupService(request.user).verify(pk)
        return Response(JobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


class RestoreView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: UUID) -> Response:
        payload = RestoreSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        job = BackupService(request.user).restore(pk, **payload.validated_data)
        return Response(JobSerializer(job).data, status=status.HTTP_202_ACCEPTED)
