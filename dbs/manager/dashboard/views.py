from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.dashboard.serializers import (
    DashboardSerializer,
    ManagerUpdateSerializer,
    moment,
)
from dbs.manager.dashboard.services import DashboardService, ManagerUpdateService


class DashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        summary = DashboardService(request.user).summary()
        return Response(DashboardSerializer(summary).data)


class AboutView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        about = DashboardService(request.user).about()
        return Response({**about, "last_export_at": moment(about["last_export_at"])})


class AboutUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(ManagerUpdateService(request.user).status())

    def post(self, request):
        payload = ManagerUpdateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        return Response(ManagerUpdateService(request.user).update(**payload.validated_data))
