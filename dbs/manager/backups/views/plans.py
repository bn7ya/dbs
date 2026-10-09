from __future__ import annotations

from uuid import UUID

from django.db.models import QuerySet
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.activity.serializers import JobSerializer
from dbs.manager.backups.models import BackupPlan
from dbs.manager.backups.serializers import (
    BackupFilterSerializer,
    BackupPlanSerializer,
    PlanCreateSerializer,
    PlanUpdateSerializer,
)
from dbs.manager.backups.services import BackupPlanService


class PlanListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = BackupPlanSerializer

    def get_queryset(self) -> QuerySet[BackupPlan]:
        query = BackupFilterSerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        return BackupPlanService(self.request.user).list(query.validated_data["server"])

    def post(self, request: Request) -> Response:
        payload = PlanCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        plan = BackupPlanService(request.user).create(**payload.validated_data)
        return Response(BackupPlanSerializer(plan).data, status=status.HTTP_201_CREATED)


class PlanDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, pk: UUID) -> Response:
        plan = BackupPlanService(request.user).get(pk)
        return Response(BackupPlanSerializer(plan).data)

    def patch(self, request: Request, pk: UUID) -> Response:
        payload = PlanUpdateSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        plan = BackupPlanService(request.user).update(pk, **payload.validated_data)
        return Response(BackupPlanSerializer(plan).data)

    def delete(self, request: Request, pk: UUID) -> Response:
        BackupPlanService(request.user).delete(pk)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PlanRunView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: UUID) -> Response:
        job = BackupPlanService(request.user).run(pk)
        return Response(JobSerializer(job).data, status=status.HTTP_202_ACCEPTED)
