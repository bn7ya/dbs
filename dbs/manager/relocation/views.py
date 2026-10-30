from __future__ import annotations

from uuid import UUID

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.activity.serializers import JobSerializer
from dbs.manager.relocation.serializers import ServerMoveSerializer
from dbs.manager.relocation.services import RelocationService


class ServerMoveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: UUID) -> Response:
        payload = ServerMoveSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        job = RelocationService(request.user).start(
            source_server=pk, **payload.validated_data
        )
        return Response(JobSerializer(job).data, status=status.HTTP_202_ACCEPTED)
