from __future__ import annotations

from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.accounts.serializers import (
    AccountCreateSerializer,
    AccountSerializer,
    AccountUpdateSerializer,
    HandOverSerializer,
)
from dbs.manager.accounts.services import AccountManagementService


class AccountListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AccountSerializer
    pagination_class = None

    def get_queryset(self):
        return AccountManagementService(self.request.user).list()

    def post(self, request):
        payload = AccountCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        service = AccountManagementService(request.user)
        account = service.create(**payload.validated_data)
        return Response(
            AccountSerializer(service.get(account.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class AccountDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        return Response(
            AccountSerializer(AccountManagementService(request.user).get(pk)).data
        )

    def patch(self, request, pk):
        payload = AccountUpdateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        service = AccountManagementService(request.user)
        changes = payload.validated_data
        if "role" in changes:
            service.set_role(pk, changes["role"])
        if "is_active" in changes:
            service.set_active(pk, changes["is_active"])
        return Response(AccountSerializer(service.get(pk)).data)


class TwoFactorResetView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        service = AccountManagementService(request.user)
        service.reset_two_factor(pk)
        return Response(AccountSerializer(service.get(pk)).data)


class PasswordExpireView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        service = AccountManagementService(request.user)
        service.require_password_change(pk)
        return Response(AccountSerializer(service.get(pk)).data)


class HandOverView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        payload = HandOverSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        service = AccountManagementService(request.user)
        account = service.hand_over(pk, **payload.validated_data)
        return Response(AccountSerializer(account).data)
