from __future__ import annotations

from django.core.cache import cache
from django.db import connection
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

PROBE_KEY = "health:probe"


class HealthView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        checks = {"database": self._database(), "cache": self._cache()}
        healthy = all(checks.values())
        return Response(
            {"status": "ok" if healthy else "degraded", "checks": checks},
            status=status.HTTP_200_OK
            if healthy
            else status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @staticmethod
    def _database():
        try:
            connection.ensure_connection()
        except Exception:
            return False
        return bool(connection.is_usable())

    @staticmethod
    def _cache():
        try:
            cache.set(PROBE_KEY, "1", timeout=5)
            return cache.get(PROBE_KEY) == "1"
        except Exception:
            return False
