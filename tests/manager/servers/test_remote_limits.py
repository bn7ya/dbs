from __future__ import annotations

import io
from datetime import timedelta

import pytest
from django.utils import timezone

from dbs.exceptions import ConnectionLost, DBSError, RemoteTimeout
from dbs.manager.servers.exceptions import (
    RemoteCommandFailed,
    RemoteCommandTimedOut,
    ServerConnectionLost,
    StreamBroken,
)
from dbs.manager.servers.gateways import (
    ContainerTarget,
    Credentials,
    DbsProfile,
    RemoteHost,
    connect,
)
from dbs.transports import RemoteResult
from dbs.transports.ssh import StreamInterrupted
from tests.manager.remote import argv_of
from tests.manager.servers.support import (
    PROJECT_DIR,
    PYTHON,
    LocalSftpSession,
    host_key_line,
)

COMPOSE = DbsProfile(
    python="python",
    manage="manage.py",
    project_dir=PROJECT_DIR,
    container=ContainerTarget(service="backend"),
)
CONTAINER = DbsProfile(
    python="python",
    manage="manage.py",
    container=ContainerTarget(engine="podman", container="shop-web-1"),
)
HOST = DbsProfile(python=PYTHON, manage="manage.py", project_dir=PROJECT_DIR)


class Session(LocalSftpSession):
    def __init__(self, *, result=(0, "", ""), failure=None) -> None:
        super().__init__()
        self.result = result
        self.failure = failure
        self.runs: list[tuple[list[str], float]] = []

    def run(self, script, *, stdin_line=None, timeout=None):
        self.runs.append((argv_of(script)[0], timeout))
        if self.failure is not None:
            raise self.failure
        return RemoteResult(*self.result)


def test_a_server_with_timeout_stops_a_command_at_its_deadline(settings):
    session = Session()

    RemoteHost(session, timeout_on_host=True).run(["sleep", "5"], timeout=60)

    [(argv, waited)] = session.runs
    assert argv == ["timeout", "-k", "30", "60", "sleep", "5"]
    assert waited == 60 + settings.REMOTE_KILL_AFTER + 5


def test_a_server_without_timeout_runs_the_command_as_given(settings):
    session = Session()

    RemoteHost(session).run(["sleep", "5"], timeout=60)

    assert session.runs == [(["sleep", "5"], 60)]


def test_a_compose_command_is_stopped_inside_the_container():
    session = Session()

    RemoteHost(session, timeout_on_host=True, timeout_in_container=True).run_manage(
        COMPOSE, ["dbs_restore", "/tmp/x.dbs"], timeout=600
    )

    [(argv, _)] = session.runs
    assert argv == [
        "docker",
        "compose",
        "exec",
        "-T",
        "backend",
        "timeout",
        "-k",
        "30",
        "600",
        "python",
        "manage.py",
        "dbs_restore",
        "/tmp/x.dbs",
    ]


def test_a_plain_container_command_is_stopped_inside_the_container():
    session = Session()

    RemoteHost(session, timeout_on_host=True, timeout_in_container=True).run_manage(
        CONTAINER, ["dbs_restore", "/tmp/x.dbs"], stdin_line="secret", timeout=600
    )

    [(argv, _)] = session.runs
    assert argv == [
        "podman",
        "exec",
        "-i",
        "shop-web-1",
        "timeout",
        "-k",
        "30",
        "600",
        "python",
        "manage.py",
        "dbs_restore",
        "/tmp/x.dbs",
    ]


def test_a_container_without_timeout_is_stopped_from_the_host():
    session = Session()

    RemoteHost(session, timeout_on_host=True).run_in_container(
        COMPOSE, ["id", "-u"], timeout=20
    )

    [(argv, _)] = session.runs
    assert argv[:5] == ["timeout", "-k", "30", "20", "docker"]
    assert argv[-2:] == ["id", "-u"]


@pytest.mark.parametrize("status", [124, 137])
def test_a_command_stopped_at_its_deadline_says_it_ran_out_of_time(status):
    remote = RemoteHost(Session(result=(status, "", "")), timeout_on_host=True)

    with pytest.raises(RemoteCommandTimedOut) as raised:
        remote.run(["python", "manage.py", "dbs_restore"])

    assert raised.value.settles_at is None


def test_an_exit_of_124_is_the_commands_own_without_timeout():
    result = RemoteHost(Session(result=(124, "", ""))).run(["false"])

    assert result.exit_status == 124


@pytest.mark.parametrize(
    ("failure", "raised"),
    [
        (RemoteTimeout("timed out"), RemoteCommandTimedOut),
        (ConnectionLost("gone"), ServerConnectionLost),
        (DBSError("broken pipe"), RemoteCommandFailed),
    ],
)
def test_a_command_whose_end_was_not_seen_settles_after_the_kill_window(
    settings, failure, raised
):
    before = timezone.now()

    with pytest.raises(raised) as caught:
        RemoteHost(Session(failure=failure)).run(["python", "manage.py"], timeout=40)

    window = timedelta(seconds=40 + settings.REMOTE_KILL_AFTER)
    assert before + window <= caught.value.settles_at <= timezone.now() + window


def test_the_timeout_probe_runs_unbounded_on_the_host_and_in_the_container():
    session = Session()
    remote = RemoteHost(session, timeout_on_host=True, timeout_in_container=True)

    assert remote.has_timeout() is True
    assert remote.has_timeout(COMPOSE) is True
    assert remote.has_timeout(CONTAINER) is True
    assert remote.has_timeout(HOST) is True

    assert [argv for argv, _ in session.runs] == [
        ["timeout", "-k", "1", "5", "true"],
        ["docker", "compose", "exec", "-T", "backend", "timeout", "-k", "1", "5", "true"],
        ["podman", "exec", "shop-web-1", "timeout", "-k", "1", "5", "true"],
        ["timeout", "-k", "1", "5", "true"],
    ]


@pytest.mark.parametrize(
    "session", [Session(result=(127, "", "timeout: not found")), Session(failure=DBSError())]
)
def test_a_server_without_timeout_says_so(session):
    assert RemoteHost(session).has_timeout() is False


def test_a_failure_on_a_dropped_connection_is_reported_as_lost(monkeypatch):
    class Dropped(LocalSftpSession):
        def __init__(self, target, on_activity=None) -> None:
            super().__init__()
            self.target = target

        def __enter__(self):
            return self

        def run(self, script, *, stdin_line=None, timeout=None):
            self.dropped = True
            raise OSError("reset by peer")

    monkeypatch.setattr("dbs.manager.servers.gateways.ssh_gateway.SSHSession", Dropped)
    credentials = Credentials(
        host="10.0.0.5",
        port=22,
        username="deploy",
        host_key=host_key_line(),
        password="secret",
    )

    with pytest.raises(ServerConnectionLost), connect(credentials) as remote:
        remote.run(["true"])


class StreamingSession(Session):
    def __init__(self, *, result=(0, "", ""), failure=None) -> None:
        super().__init__(result=result, failure=failure)
        self.streams: list[tuple[list[str], float]] = []

    def stream(
        self,
        script,
        sink,
        *,
        stdin_line=None,
        timeout=None,
        progress=None,
        idle_timeout=None,
        on_stderr_line=None,
    ):
        self.streams.append((argv_of(script)[0], timeout))
        if self.failure is not None:
            raise self.failure
        return RemoteResult(*self.result)


def streamed(session, profile=HOST, **limits):
    return RemoteHost(session, **limits).stream_dbs_backup(
        profile, passphrase="secret", prefix="web-1", folder="", sink=io.BytesIO()
    )


def test_a_streamed_backup_is_stopped_at_the_backup_deadline(settings):
    settings.BACKUP_TOTAL_TIMEOUT = 3600
    session = StreamingSession(result=(124, "", "Terminated"))

    with pytest.raises(RemoteCommandTimedOut):
        streamed(session, timeout_on_host=True)

    [(argv, waited)] = session.streams
    assert argv[:5] == ["timeout", "-k", "30", "3600", PYTHON]
    assert argv[5:8] == ["manage.py", "dbs_backup", "--stream"]
    assert waited == 3600 + settings.REMOTE_KILL_AFTER + 5


def test_a_streamed_compose_backup_is_stopped_inside_the_container(settings):
    settings.BACKUP_TOTAL_TIMEOUT = 3600
    session = StreamingSession(result=(137, "", ""))

    with pytest.raises(RemoteCommandTimedOut):
        streamed(session, COMPOSE, timeout_on_host=True, timeout_in_container=True)

    [(argv, _)] = session.streams
    assert argv[:5] == ["docker", "compose", "exec", "-T", "backend"]
    assert argv[5:10] == ["timeout", "-k", "30", "3600", "python"]


def test_a_streamed_backup_without_timeout_waits_the_backup_deadline(settings):
    settings.BACKUP_TOTAL_TIMEOUT = 3600
    session = StreamingSession(result=(124, "", ""))

    with pytest.raises(RemoteCommandFailed) as failed:
        streamed(session)

    assert type(failed.value) is RemoteCommandFailed
    [(argv, waited)] = session.streams
    assert argv[0] == PYTHON
    assert waited == 3600


def test_a_stream_that_breaks_under_timeout_is_still_kept_on_the_server():
    session = StreamingSession(failure=StreamInterrupted("The connection was lost: "))

    with pytest.raises(StreamBroken):
        streamed(session, timeout_on_host=True)
