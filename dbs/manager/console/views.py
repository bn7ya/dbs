from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.console.serializers import (
    ConsoleRequestSerializer,
    ConsoleResultSerializer,
)
from dbs.manager.console.service import ConsoleService


class ConsoleView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        payload = ConsoleRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        result = ConsoleService(request.user).run(**payload.validated_data)
        return Response(
            ConsoleResultSerializer(result).data, headers={"Cache-Control": "no-store"}
        )
