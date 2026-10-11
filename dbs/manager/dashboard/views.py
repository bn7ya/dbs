from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.dashboard.serializers import DashboardSerializer, moment
from dbs.manager.dashboard.services import DashboardService


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
