from __future__ import annotations

from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.activity.serializers import (
    ActivityFilterSerializer,
    ActivitySerializer,
)
from dbs.manager.activity.services import ActivityService


class ActivityListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ActivitySerializer

    def get_queryset(self):
        filters = ActivityFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return ActivityService(self.request.user).list(**filters.validated_data)

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        servers = ActivityService(request.user).servers_for(page)
        data = ActivitySerializer(page, many=True, context={"servers": servers}).data
        return self.get_paginated_response(data)


class ActivityDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        service = ActivityService(request.user)
        entry = service.get(pk)
        servers = service.servers_for([entry])
        return Response(ActivitySerializer(entry, context={"servers": servers}).data)
