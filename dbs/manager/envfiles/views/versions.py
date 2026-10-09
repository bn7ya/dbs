from __future__ import annotations

from uuid import UUID

from django.db.models import QuerySet
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.envfiles.models import EnvVersion
from dbs.manager.envfiles.serializers import (
    EnvCompareQuerySerializer,
    EnvComparisonSerializer,
    EnvFilterSerializer,
    EnvVersionSerializer,
)
from dbs.manager.envfiles.services import EnvFileService


class EnvVersionListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EnvVersionSerializer

    def get_queryset(self) -> QuerySet[EnvVersion]:
        query = EnvFilterSerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        return EnvFileService(self.request.user).list(query.validated_data["server"])


class EnvVersionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, pk: UUID) -> Response:
        return Response(EnvVersionSerializer(EnvFileService(request.user).get(pk)).data)


class EnvCompareView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, pk: UUID) -> Response:
        query = EnvCompareQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        comparison = EnvFileService(request.user).compare(
            pk, query.validated_data["to"]
        )
        return Response(EnvComparisonSerializer(comparison).data)
