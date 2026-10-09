from __future__ import annotations

from rest_framework import serializers

from dbs.manager.envfiles.models import EnvVersion


class EnvVersionSerializer(serializers.ModelSerializer):
    server = serializers.UUIDField(source="server_id", read_only=True)
    keys = serializers.ListField(
        source="key_names",
        child=serializers.CharField(),
        read_only=True,
    )
    taken_by = serializers.CharField(
        source="created_by.username",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = EnvVersion
        fields = [
            "id",
            "server",
            "path",
            "size",
            "keys",
            "source",
            "created_at",
            "taken_by",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "path": {
                "help_text": "Where the file was on the server: its `env_path` then."
            },
            "size": {"help_text": "Bytes."},
            "source": {
                "help_text": (
                    "`pulled` by a person, or kept by a push just before it wrote; "
                    "`pushed`, what a push wrote; `scheduled`, the daily snapshot."
                )
            },
        }


class EnvPulledSerializer(serializers.Serializer):
    created = serializers.BooleanField(
        read_only=True,
    )
    version = EnvVersionSerializer(read_only=True)


class EnvPushedSerializer(serializers.Serializer):
    version = EnvVersionSerializer(
        read_only=True,
    )


class EnvRevealedSerializer(serializers.Serializer):
    content = serializers.CharField(
        read_only=True,
        trim_whitespace=False,
    )


def _names(help_text: str) -> serializers.ListField:
    return serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )


class EnvComparisonSerializer(serializers.Serializer):
    to = serializers.UUIDField(
        source="to_id",
        read_only=True,
    )
    added = _names("Names in `to` and not in `from`, in `to`'s order.")
    removed = _names("Names in `from` and not in `to`, in `from`'s order.")
    changed = _names(
        "Names in both whose value differs, in `to`'s order. Never a value."
    )

    def get_fields(
        self,
    ) -> dict[str, serializers.Field[object, object, object, object]]:
        compared = serializers.UUIDField(
            source="from_id",
            read_only=True,
        )
        return {"from": compared, **super().get_fields()}
