from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.activity.serializers import JobSerializer
from dbs.manager.redeploy.serializers import RedeploySerializer
from dbs.manager.redeploy.services import RedeployService


class RedeployView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        payload = RedeploySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        job = RedeployService(request.user).start(**payload.validated_data)
        return Response(JobSerializer(job).data, status=status.HTTP_202_ACCEPTED)
