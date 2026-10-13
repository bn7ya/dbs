from __future__ import annotations

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.accounts.serializers import (
    CodeSerializer,
    EnrollmentSerializer,
    EnrollSerializer,
    IdentitySerializer,
    SignedInSerializer,
)
from dbs.manager.accounts.services import AccountService, SignInService


class TwoFactorView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        payload = CodeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        user = SignInService(request).second_factor(**payload.validated_data)
        return Response(IdentitySerializer(AccountService(user).identity()).data)


class EnrollmentView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        enrollment = SignInService(request).enrollment()
        return Response(EnrollmentSerializer(enrollment).data)


class EnrollmentConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        payload = EnrollSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        user, codes = SignInService(request).enroll(**payload.validated_data)
        signed_in = {
            "identity": AccountService(user).identity(),
            "recovery_codes": codes,
        }
        return Response(SignedInSerializer(signed_in).data)
