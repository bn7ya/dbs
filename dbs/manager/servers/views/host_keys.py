from __future__ import annotations

from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.servers.serializers import HostKeyConfirmationSerializer
from dbs.manager.servers.services import HostKeyConfirmationService
from dbs.manager.servers.services.host_key_confirmation_service import (
    HostKeyConfirmation,
)


class HostKeyConfirmationListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HostKeyConfirmationSerializer

    def get_queryset(self) -> list[HostKeyConfirmation]:
        return HostKeyConfirmationService(self.request.user).pending()


class HostKeyConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, confirmation: str) -> Response:
        confirmed = HostKeyConfirmationService(request.user).confirm(confirmation)
        return Response(HostKeyConfirmationSerializer(confirmed).data)


class HostKeyRejectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, confirmation: str) -> Response:
        rejected = HostKeyConfirmationService(request.user).reject(confirmation)
        return Response(HostKeyConfirmationSerializer(rejected).data)
