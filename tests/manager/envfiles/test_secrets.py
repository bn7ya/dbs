from __future__ import annotations

import hashlib
import json
import logging

import pytest

from dbs.manager.activity.repositories import ActivityRepository
from tests.manager.envfiles.conftest import DB_PASSWORD, ENV, LIST, SECRET
from tests.manager.servers.support import PASSWORD

VALUES = (SECRET, DB_PASSWORD)


def holds_a_value(text: str) -> bool:
    return any(value in text for value in VALUES)


@pytest.mark.django_db
def test_no_value_reaches_a_response_the_log_or_a_column_but_through_a_reveal(
    api, anonymous, caplog, settings, server, env_file, network, versions
):
    caplog.set_level(logging.DEBUG)
    bodies = []

    def answered(response):
        bodies.append(response.content.decode())
        return response.json()

    first = answered(api.post(f"{LIST}pull/", {"server": server.pk}))["version"]["id"]
    answered(api.post(f"{LIST}pull/", {"server": server.pk}))
    env_file.write_bytes(ENV + b"ADDED=1\n")
    second = answered(api.post(f"{LIST}pull/", {"server": server.pk}))["version"]["id"]
    answered(api.get(LIST, {"server": server.pk}))
    answered(api.get(f"{LIST}{first}/"))
    answered(api.get(f"{LIST}{first}/compare/", {"to": second}))
    answered(api.post(f"{LIST}{first}/reveal/", {"password": "wrong"}))
    answered(anonymous.post(f"{LIST}{first}/reveal/", {"password": PASSWORD}))
    answered(api.post(f"{LIST}{first}/push/", {"password": "wrong"}))
    answered(api.post(f"{LIST}{first}/push/", {"password": PASSWORD}))
    network.unreachable.add(server.host)
    answered(api.post(f"{LIST}pull/", {"server": server.pk}))
    answered(api.post(f"{LIST}{second}/push/", {"password": PASSWORD}))
    network.unreachable.clear()
    settings.ENV_MAX_BYTES = 8
    answered(api.post(f"{LIST}pull/", {"server": server.pk}))
    answered(api.post(f"{LIST}{second}/push/", {"password": PASSWORD}))
    revealed = api.post(f"{LIST}{second}/reveal/", {"password": PASSWORD})
    log = api.get("/api/activity/", {"page_size": 200})

    assert holds_a_value(revealed.json()["content"])
    assert len(bodies) == 14
    assert not any(holds_a_value(body) for body in bodies)
    assert not holds_a_value(log.content.decode())
    entries = list(ActivityRepository().filtered())
    assert {entry.action for entry in entries} >= {"env.pull", "env.reveal", "env.push"}
    for entry in entries:
        assert not holds_a_value(
            json.dumps([entry.target_name, entry.data, entry.error_code])
        )
    assert not holds_a_value(caplog.text)
    for version in versions(server):
        stored = bytes(version.content_sealed)
        assert not any(value.encode() in stored for value in VALUES)
        assert version.fingerprint != hashlib.sha256(ENV).hexdigest()
        assert not holds_a_value(" ".join(version.key_names))
