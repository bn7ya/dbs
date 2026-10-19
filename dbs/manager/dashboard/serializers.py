from __future__ import annotations

from rest_framework import serializers
from rest_framework.fields import DateTimeField

from dbs.manager.activity.serializers import ActivitySerializer

MOMENT = DateTimeField()


def moment(value):
    return None if value is None else MOMENT.to_representation(value)


def _application(application):
    last = application["last_backup"]
    if last is not None:
        last = {**last, "created_at": moment(last["created_at"])}
    return {
        **application,
        "checked_at": moment(application["checked_at"]),
        "next_plan_run": moment(application["next_plan_run"]),
        "last_backup": last,
    }


class DashboardSerializer(serializers.BaseSerializer):
    def to_representation(self, instance):
        servers = [
            {
                **server,
                "checked_at": moment(server["checked_at"]),
                "last_seen_at": moment(server["last_seen_at"]),
                "applications": [
                    _application(application)
                    for application in server["applications"]
                ],
            }
            for server in instance["servers"]
        ]
        failures = ActivitySerializer(
            instance["recent_failures"],
            many=True,
            context={"subjects": instance["recent_failure_subjects"]},
        ).data
        return {
            "servers": servers,
            "storage_bytes": instance["storage_bytes"],
            "disk": instance["disk"],
            "last_export_at": moment(instance["last_export_at"]),
            "recent_failures": failures,
            "key_store": instance["key_store"],
        }
