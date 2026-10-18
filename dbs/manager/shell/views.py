from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.shell.serializers import (
    InputSerializer,
    OutputQuerySerializer,
    ResizeSerializer,
    TerminalOpenSerializer,
    TerminalSerializer,
)
from dbs.manager.shell.service import ShellService

UNBUFFERED = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}


def service(request: Request) -> ShellService:
    return ShellService(request.user, request.session.session_key or "")


class TerminalListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(
            {"results": TerminalSerializer(service(request).list(), many=True).data}
        )

    def post(self, request: Request) -> Response:
        payload = TerminalOpenSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        session = service(request).open(**payload.validated_data)
        return Response(
            TerminalSerializer(session).data,
            status=status.HTTP_201_CREATED,
            headers={"Cache-Control": "no-store"},
        )


class TerminalDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request: Request, identifier: str) -> Response:
        service(request).close(identifier)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TerminalOutputView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, identifier: str) -> Response:
        query = OutputQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        found = service(request).output(identifier, query.validated_data["cursor"])
        return Response(found, headers=UNBUFFERED)


class TerminalInputView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, identifier: str) -> Response:
        payload = InputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        sent = service(request).input(identifier, **payload.validated_data)
        return Response({"accepted": sent}, headers={"Cache-Control": "no-store"})


class TerminalResizeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, identifier: str) -> Response:
        payload = ResizeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        session = service(request).resize(identifier, **payload.validated_data)
        return Response(TerminalSerializer(session).data)
