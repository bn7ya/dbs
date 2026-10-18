from __future__ import annotations

from contextlib import contextmanager

import pytest

from dbs import audit
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.backups.services import BackupService
from dbs.manager.backups.services import dbs_runs
from dbs.manager.servers.exceptions import SSHUnreachable
from tests.manager.backups.support import BackupHost
from tests.manager.servers.support import BACKUP_PASSPHRASE, connecting_to, dbs_backup

CONNECT = "dbs.manager.servers.services.connection_service.connect"
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(dbs_runs, "RECONNECT_WAITS", (0.0, 0.0, 0.0))
    monkeypatch.setattr(dbs_runs, "FINISH_POLL_SECONDS", 0.0)


@pytest.fixture
def content(db) -> bytes:
    return dbs_backup(BACKUP_PASSPHRASE)


@pytest.fixture
def reporting(application):
    return ApplicationRepository().update(
        application, last_check_report={"dbs_version": "0.8.0"}
    )


@pytest.fixture
def take(admin, application, run_jobs, entry):
    def run():
        with run_jobs():
            job = BackupService(admin).take(application.pk)
        return entry(job.pk)

    return run


def hosting(monkeypatch, server_root, content, **options) -> BackupHost:
    host = BackupHost(root=server_root, content=content, breaks=True, **options)
    monkeypatch.setattr(CONNECT, connecting_to(host))
    return host


def answering_after(monkeypatch, host: BackupHost, refusals: int) -> list:
    attempts = []

    @contextmanager
    def connect(credentials):
        attempts.append(credentials)
        if 1 < len(attempts) <= 1 + refusals:
            raise SSHUnreachable()
        host.credentials = credentials
        yield host

    monkeypatch.setattr(CONNECT, connect)
    return attempts


def stored(job) -> BackupFile:
    return BackupFileRepository().get(job.data["backup"])


def test_a_broken_stream_is_resumed_from_where_it_stopped(
    monkeypatch, reporting, server_root, content, take, storage
):
    host = hosting(monkeypatch, server_root, content)

    job = take()

    assert job.status == audit.SUCCEEDED, job.data
    assert job.data["resumed"] is True
    backup = stored(job)
    assert backup.validation == BackupFile.Validation.VERIFIED
    assert (storage / backup.storage_path).read_bytes() == content
    assert host.offsets == [len(content) // 2]
    assert host.remote_names() == []


def test_a_backup_the_server_is_still_writing_is_waited_for(
    monkeypatch, reporting, server_root, content, take, storage
):
    host = hosting(monkeypatch, server_root, content, still_writing=3)

    job = take()

    assert job.status == audit.SUCCEEDED, job.data
    assert job.data["resumed"] is True
    assert host.listings >= 4
    assert (storage / stored(job).storage_path).read_bytes() == content
    assert host.offsets == [len(content) // 2]


def test_bytes_that_arrived_changed_are_pulled_again_whole(
    monkeypatch, reporting, server_root, content, take, storage
):
    host = hosting(monkeypatch, server_root, content, sent=bytes(reversed(content)))

    job = take()

    assert job.status == audit.SUCCEEDED, job.data
    backup = stored(job)
    assert backup.validation == BackupFile.Validation.VERIFIED
    assert (storage / backup.storage_path).read_bytes() == content
    assert host.offsets == [len(content) // 2, 0]


def test_a_server_that_answers_again_on_a_later_try_is_resumed(
    monkeypatch, reporting, server_root, content, take
):
    host = BackupHost(root=server_root, content=content, breaks=True)
    attempts = answering_after(monkeypatch, host, refusals=2)

    job = take()

    assert job.status == audit.SUCCEEDED, job.data
    assert job.data["resumed"] is True
    assert len(attempts) == 4


def test_a_server_that_never_answers_again_keeps_the_backup_for_next_time(
    monkeypatch, reporting, server_root, content, take, application
):
    host = BackupHost(root=server_root, content=content, breaks=True)
    attempts = answering_after(monkeypatch, host, refusals=3)

    job = take()

    assert job.status == audit.SUCCEEDED
    assert job.data == {"outcome": "kept_on_server", "pulled": 0}
    assert len(attempts) == 4
    assert len(host.remote_names()) == 1
    assert list(BackupFileRepository().alive_for_application(application.pk)) == []


def test_a_writer_that_stopped_writing_leaves_the_backup_on_the_server(
    monkeypatch, settings, reporting, server_root, content, take
):
    settings.BACKUP_IDLE_TIMEOUT = 0
    host = hosting(monkeypatch, server_root, content, never_finishes=True)

    job = take()

    assert job.data == {"outcome": "kept_on_server", "pulled": 0}
    assert host.offsets == []


def test_a_backup_the_server_gave_up_on_fails_the_take(
    monkeypatch, reporting, server_root, content, take, storage, application
):
    hosting(monkeypatch, server_root, content, discards=True)

    job = take()

    assert (job.status, job.error_code) == (audit.FAILED, "backup_lost_on_server")
    assert list(BackupFileRepository().alive_for_application(application.pk)) == []
    assert [path.name for path in (storage / str(application.pk)).iterdir()] == []


def test_an_older_server_that_names_nothing_keeps_the_backup_for_next_time(
    monkeypatch, server_root, content, take
):
    host = hosting(monkeypatch, server_root, content)

    job = take()

    assert job.data == {"outcome": "kept_on_server", "pulled": 0}
    assert host.listings == 0 and host.offsets == []
