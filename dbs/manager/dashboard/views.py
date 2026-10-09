from __future__ import annotations

from rest_framework.fields import DateTimeField
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dbs.manager.activity.serializers import ActivitySerializer
from dbs.manager.dashboard.services import DashboardService

MOMENT = DateTimeField()


def _moment(value):
    return None if value is None else MOMENT.to_representation(value)


class DashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        summary = DashboardService(request.user).summary()
        servers = []
        for server in summary["servers"]:
            last = server["last_backup"]
            if last is not None:
                last = {**last, "created_at": _moment(last["created_at"])}
            servers.append(
                {
                    **server,
                    "checked_at": _moment(server["checked_at"]),
                    "next_plan_run": _moment(server["next_plan_run"]),
                    "last_backup": last,
                }
            )
        failures = ActivitySerializer(
            summary["recent_failures"],
            many=True,
            context={"servers": summary["recent_failure_servers"]},
        ).data
        return Response(
            {
                "servers": servers,
                "storage_bytes": summary["storage_bytes"],
                "last_export_at": _moment(summary["last_export_at"]),
                "recent_failures": failures,
            }
        )


class AboutView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        about = DashboardService(request.user).about()
        return Response({**about, "last_export_at": _moment(about["last_export_at"])})
