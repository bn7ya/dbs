from __future__ import annotations

from rest_framework import serializers
from rest_framework.fields import DateTimeField

from dbs.manager.activity.serializers import ActivitySerializer

MOMENT = DateTimeField()


def moment(value):
    return None if value is None else MOMENT.to_representation(value)


class DashboardSerializer(serializers.BaseSerializer):
    def to_representation(self, instance):
        servers = []
        for server in instance["servers"]:
            last = server["last_backup"]
            if last is not None:
                last = {**last, "created_at": moment(last["created_at"])}
            servers.append(
                {
                    **server,
                    "checked_at": moment(server["checked_at"]),
                    "next_plan_run": moment(server["next_plan_run"]),
                    "last_backup": last,
                }
            )
        failures = ActivitySerializer(
            instance["recent_failures"],
            many=True,
            context={"servers": instance["recent_failure_servers"]},
        ).data
        return {
            "servers": servers,
            "storage_bytes": instance["storage_bytes"],
            "last_export_at": moment(instance["last_export_at"]),
            "recent_failures": failures,
            "key_store": instance["key_store"],
        }
