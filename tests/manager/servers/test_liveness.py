from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta

import pytest
from django.utils import timezone

from dbs.manager.activity import heartbeat
from dbs.manager.activity.services import ActivityService
from dbs.manager.backups.locks import TakeLock
from dbs.manager.servers import settling
from dbs.manager.servers.exceptions import (
    RemoteCommandFailed,
    ServerConnectionLost,
    SSHUnreachable,
)
from dbs.manager.servers.models import Server
from dbs.manager.servers.repositories import ServerRepository
from dbs.manager.servers.services import ServerConnectionService, ServerService
from dbs.manager.servers.services.connection_service import probe_servers
from tests.manager.servers.support import (
    Result,
    connecting_to,
    healthy_remote,
    refusing_with,
)

CONNECT = "dbs.manager.servers.services.connection_service.connect"


def fresh(server: Server) -> Server:
    return ServerRepository().get(server.pk)


@pytest.mark.django_db
def test_a_server_starts_unknown(configured_server):
    assert configured_server.connection_state == Server.ConnectionState.UNKNOWN
    assert configured_server.last_seen_at is None


@pytest.mark.django_db
def test_every_connection_marks_the_server_online(admin, monkeypatch, configured_server):
    monkeypatch.setattr(CONNECT, connecting_to(healthy_remote()))
    before = timezone.now()

    with ServerConnectionService(admin).open(configured_server):
        pass

    seen = fresh(configured_server)
    assert seen.connection_state == Server.ConnectionState.ONLINE
    assert seen.last_seen_at >= before
    assert seen.last_connection_error == ""


@pytest.mark.django_db
def test_a_server_that_does_not_answer_is_offline_and_keeps_when_it_was_seen(
    admin, monkeypatch, configured_server
):
    monkeypatch.setattr(CONNECT, connecting_to(healthy_remote()))
    connections = ServerConnectionService(admin)
    with connections.open(configured_server):
        pass
    seen_at = fresh(configured_server).last_seen_at
    monkeypatch.setattr(CONNECT, refusing_with(SSHUnreachable()))

    with pytest.raises(SSHUnreachable), connections.open(configured_server.pk):
        pass

    gone = fresh(configured_server)
    assert gone.connection_state == Server.ConnectionState.OFFLINE
    assert gone.last_connection_error == "ssh_unreachable"
    assert gone.last_seen_at == seen_at


@pytest.mark.django_db
def test_a_connection_lost_mid_work_marks_the_server_offline_and_settling(
    admin, monkeypatch, configured_server
):
    monkeypatch.setattr(CONNECT, connecting_to(healthy_remote()))
    until = timezone.now() + timedelta(minutes=1)

    with pytest.raises(ServerConnectionLost):
        with ServerConnectionService(admin).open(configured_server):
            raise ServerConnectionLost(settles_at=until)

    assert fresh(configured_server).connection_state == Server.ConnectionState.OFFLINE
    assert fresh(configured_server).last_connection_error == "connection_lost"
    assert settling.settling_until(configured_server.pk) == until


@pytest.mark.django_db
def test_a_command_that_failed_on_its_own_leaves_the_server_online(
    admin, monkeypatch, configured_server
):
    monkeypatch.setattr(CONNECT, connecting_to(healthy_remote()))

    with pytest.raises(RemoteCommandFailed):
        with ServerConnectionService(admin).open(configured_server):
            raise RemoteCommandFailed()

    assert fresh(configured_server).connection_state == Server.ConnectionState.ONLINE
    assert settling.settling_until(configured_server.pk) is None


@pytest.mark.django_db
def test_no_new_job_starts_while_a_stopped_command_may_still_run(
    admin, api, monkeypatch, configured_server
):
    settling.mark(configured_server.pk, timezone.now() + timedelta(seconds=45))

    response = api.post("/api/backups/take/", {"server": str(configured_server.pk)})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "server_settling"
    assert TakeLock().acquire(configured_server.pk, 1) is False


@pytest.mark.django_db
def test_a_window_that_has_passed_holds_nothing(configured_server):
    settling.mark(configured_server.pk, timezone.now() - timedelta(seconds=1))

    assert settling.settling_until(configured_server.pk) is None
    assert TakeLock().acquire(configured_server.pk, 1) is True


@pytest.mark.django_db
def test_a_later_window_is_never_shortened(configured_server):
    later = timezone.now() + timedelta(minutes=2)
    settling.mark(configured_server.pk, later)
    settling.mark(configured_server.pk, timezone.now() + timedelta(seconds=10))

    assert settling.settling_until(configured_server.pk) == later


@pytest.mark.django_db
def test_a_job_hands_its_heartbeat_to_the_connection(admin, monkeypatch, configured_server):
    remote = healthy_remote()
    monkeypatch.setattr(CONNECT, connecting_to(remote))
    queued = ActivityService(admin).queue("backup.take", server=configured_server)
    job = ActivityService(None).start(queued.pk)
    pulse = heartbeat.current()

    try:
        with ServerConnectionService(admin).open(configured_server):
            assert remote.credentials.on_activity is pulse
            pulse(2048)
            during = heartbeat.connection_of(job.pk)
        after = heartbeat.connection_of(job.pk)
    finally:
        ActivityService(None).succeed(job.pk)

    assert during["state"] == heartbeat.ALIVE and during["bytes"] == 2048
    assert after is None
    assert heartbeat.current() is None
    assert heartbeat.connection_of(job.pk) is None


@pytest.mark.django_db
def test_a_running_job_shows_whether_its_connection_is_alive(
    admin, api, monkeypatch, configured_server, settings
):
    queued = ActivityService(admin).queue("backup.take", server=configured_server)
    job = ActivityService(None).start(queued.pk)
    pulse = heartbeat.current()
    url = f"/api/activity/{job.pk}/"
    try:
        assert api.get(url).json()["connection"] is None
        with pulse.connected():
            alive = api.get(url).json()["connection"]
            pulse.heard_at = timezone.now() - timedelta(
                seconds=4 * settings.SSH_KEEPALIVE_INTERVAL
            )
            lost = api.get(url).json()["connection"]
    finally:
        ActivityService(None).succeed(job.pk)

    assert alive["state"] == "alive" and alive["bytes"] == 0
    assert lost["state"] == "lost"
    assert api.get(url).json()["connection"] is None


@pytest.mark.django_db
def test_the_probe_reaches_servers_not_seen_lately(admin, monkeypatch, configured_server):
    remote = healthy_remote()
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    assert probe_servers() == 1

    assert [run["argv"] for run in remote.runs] == [["true"]]
    assert fresh(configured_server).connection_state == Server.ConnectionState.ONLINE
    assert probe_servers() == 0


@pytest.mark.django_db
def test_the_probe_marks_a_silent_server_offline(admin, monkeypatch, configured_server):
    monkeypatch.setattr(CONNECT, refusing_with(SSHUnreachable()))

    assert probe_servers() == 1

    assert fresh(configured_server).connection_state == Server.ConnectionState.OFFLINE
    assert probe_servers() == 1


@pytest.mark.django_db
def test_a_server_is_never_probed_twice_at_once(admin, monkeypatch, configured_server):
    probing = []

    @contextmanager
    def connect(credentials):
        probing.append(credentials.host)
        assert probe_servers() == 0
        yield healthy_remote()

    monkeypatch.setattr(CONNECT, connect)

    assert ServerConnectionService(None).probe(configured_server) is True
    assert probing == ["10.0.0.5"]


@pytest.mark.django_db
def test_the_check_remembers_whether_commands_can_be_stopped(
    admin, monkeypatch, configured_server
):
    remote = healthy_remote()
    remote.answers = {**remote.answers, ("timeout", "-k", "1", "5", "true"): Result(0)}
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    checked = ServerService(admin).check(configured_server.pk)

    assert (checked.timeout_on_host, checked.timeout_in_container) == (True, None)
    with ServerConnectionService(admin).open(checked) as opened:
        assert opened.credentials.timeout_on_host is True
