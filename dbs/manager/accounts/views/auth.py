from __future__ import annotations

from django.contrib.auth import update_session_auth_hash
from django.middleware.csrf import get_token
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.accounts.serializers import (
    IdentitySerializer,
    PasswordChangeSerializer,
    PasswordConfirmSerializer,
    RecoveryCodesSerializer,
    SetupSerializer,
    SignInSerializer,
    SignInStepSerializer,
)
from dbs.manager.accounts.services import AccountService, SetupService, SignInService


class CsrfView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"csrf_token": get_token(request)})


class SignInView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        payload = SignInSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        step = SignInService(request).password(**payload.validated_data)
        return Response(SignInStepSerializer({"step": step}).data)


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


class PasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        payload = PasswordChangeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        service = AccountService(request.user)
        user = service.change_password(**payload.validated_data)
        update_session_auth_hash(request, user)
        return Response(IdentitySerializer(service.identity()).data)


class RecoveryCodesView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        payload = PasswordConfirmSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        codes = AccountService(request.user).new_recovery_codes(
            payload.validated_data["password"]
        )
        return Response(RecoveryCodesSerializer({"recovery_codes": codes}).data)


class SetupView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"needed": SetupService().needed()})

    def post(self, request):
        payload = SetupSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        user, step = SetupService().complete(request, **payload.validated_data)
        return Response(
            {"username": user.get_username(), "step": step},
            status=status.HTTP_201_CREATED,
        )
