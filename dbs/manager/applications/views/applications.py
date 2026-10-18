from __future__ import annotations

from uuid import UUID

from django.db.models import QuerySet
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.applications.models import Application
from dbs.manager.applications.serializers import (
    ApplicationCreateSerializer,
    ApplicationFilterSerializer,
    ApplicationListSerializer,
    ApplicationSerializer,
    ApplicationUpdateSerializer,
    CheckedApplicationSerializer,
    DiscoverRequestSerializer,
)
from dbs.manager.applications.services import ApplicationService, DiscoveryService
from dbs.manager.redeploy.serializers import DeployStepsSerializer
from dbs.manager.servers.serializers import (
    AccountPasswordSerializer,
    PassphraseSerializer,
    PasswordSerializer,
)


class ApplicationListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ApplicationListSerializer

    def get_queryset(self) -> QuerySet[Application]:
        filters = ApplicationFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return ApplicationService(self.request.user).list(**filters.validated_data)

    def post(self, request: Request) -> Response:
        payload = ApplicationCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        application = ApplicationService(request.user).create(**payload.validated_data)
        return Response(
            ApplicationSerializer(application).data, status=status.HTTP_201_CREATED
        )


class ApplicationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, pk: UUID) -> Response:
        application = ApplicationService(request.user).get(pk)
        return Response(ApplicationSerializer(application).data)

    def patch(self, request: Request, pk: UUID) -> Response:
        payload = ApplicationUpdateSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        application = ApplicationService(request.user).update(
            pk, **payload.validated_data
        )
        return Response(ApplicationSerializer(application).data)

    def delete(self, request: Request, pk: UUID) -> Response:
        payload = AccountPasswordSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        ApplicationService(request.user).delete(pk, **payload.validated_data)
        return Response(status=status.HTTP_204_NO_CONTENT)


class DiscoverView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        payload = DiscoverRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        server = data.pop("server")
        return Response(DiscoveryService(request.user).discover(server, **data))


class CheckView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: UUID) -> Response:
        checked = ApplicationService(request.user).checked(pk)
        return Response(CheckedApplicationSerializer(checked).data)


class PassphraseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: UUID) -> Response:
        payload = PasswordSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        passphrase = ApplicationService(request.user).reveal_passphrase(
            pk, **payload.validated_data
        )
        return Response(
            PassphraseSerializer({"passphrase": passphrase}).data,
            headers={"Cache-Control": "no-store"},
        )


class PassphraseCaptureView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: UUID) -> Response:
        ApplicationService(request.user).capture_passphrase(pk)
        return Response({"captured": True})


class DeployStepsView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request: Request, pk: UUID) -> Response:
        payload = DeployStepsSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        application = ApplicationService(request.user).set_deploy_steps(
            pk, **payload.validated_data
        )
        return Response(ApplicationSerializer(application).data)
