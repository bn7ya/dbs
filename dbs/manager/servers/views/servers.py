from __future__ import annotations

from uuid import UUID

from django.db.models import QuerySet
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.servers.models import Server
from dbs.manager.servers.serializers import (
    AddedServerSerializer,
    ServerCreateSerializer,
    ServerListSerializer,
    ServerSerializer,
    ServerUpdateSerializer,
)
from dbs.manager.servers.services import ServerService


class ServerListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ServerListSerializer

    def get_queryset(self) -> QuerySet[Server]:
        return ServerService(self.request.user).list(
            self.request.query_params.get("search")
        )

    def post(self, request: Request) -> Response:
        payload = ServerCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        added = ServerService(request.user).add(**payload.validated_data)
        return Response(
            AddedServerSerializer(added).data, status=status.HTTP_201_CREATED
        )


class ServerDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, pk: UUID) -> Response:
        server = ServerService(request.user).get(pk)
        return Response(ServerSerializer(server).data)

    def patch(self, request: Request, pk: UUID) -> Response:
        payload = ServerUpdateSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        server = ServerService(request.user).update(pk, **payload.validated_data)
        return Response(ServerSerializer(server).data)

    def delete(self, request: Request, pk: UUID) -> Response:
        ServerService(request.user).delete(pk)
        return Response(status=status.HTTP_204_NO_CONTENT)
