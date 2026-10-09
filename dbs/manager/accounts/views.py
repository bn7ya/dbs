from __future__ import annotations

from django.middleware.csrf import get_token
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.accounts.serializers import (
    IdentitySerializer,
    SetupSerializer,
    SignInSerializer,
)
from dbs.manager.accounts.services import AccountService, SetupService


class CsrfView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        get_token(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SignInView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        payload = SignInSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        user = AccountService().sign_in(request, **payload.validated_data)
        return Response(IdentitySerializer(AccountService(user).identity()).data)


class SignOutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        AccountService(request.user).sign_out(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            IdentitySerializer(AccountService(request.user).identity()).data
        )


class SetupView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"needed": SetupService().needed()})

    def post(self, request):
        payload = SetupSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        user = SetupService().complete(request, **payload.validated_data)
        return Response(
            {"username": user.get_username()}, status=status.HTTP_201_CREATED
        )
