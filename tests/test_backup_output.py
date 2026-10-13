import errno
import os
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from dbs.engine import backup as backup_engine
from dbs.engine import create_backup, validate_backup
from dbs.exceptions import BackupError, CorruptionError
from tests.conftest import FAST_KDF
from tests.testapp.models import Author

PASS = "backup-output-pass-phrase"

FAST = {"kdf_time": 1, "kdf_memory": 8192}


@pytest.fixture
def ada(db):
    return Author.objects.create(name="Ada")


def test_an_existing_output_is_refused_and_left_alone(ada, tmp_path):
    output = tmp_path / "nightly.dbs"
    output.write_bytes(b"yesterday")

    with pytest.raises(BackupError) as refused:
        create_backup(PASS, kdf_params=FAST_KDF, output=str(output))

    assert str(output) in str(refused.value)
    assert output.read_bytes() == b"yesterday"
    assert sorted(tmp_path.iterdir()) == [output]


def test_a_failed_verification_leaves_nothing_under_the_final_name(ada, tmp_path, monkeypatch):
    output = tmp_path / "broken.dbs"

    def fail(container, passphrase, payload_sha):
        raise CorruptionError("verify-after-write failed")

    monkeypatch.setattr(backup_engine, "_verify_after_write", fail)

    with pytest.raises(CorruptionError):
        create_backup(PASS, kdf_params=FAST_KDF, output=str(output))

    assert list(tmp_path.iterdir()) == []


def test_the_temporary_file_is_verified_before_it_takes_the_final_name(ada, tmp_path, monkeypatch):
    output = tmp_path / "checked.dbs"
    seen = []
    real = backup_engine._verify_after_write

    def watch(container, passphrase, payload_sha):
        seen.append(output.exists())
        real(container, passphrase, payload_sha)

    monkeypatch.setattr(backup_engine, "_verify_after_write", watch)

    container = create_backup(PASS, kdf_params=FAST_KDF, output=str(output))

    assert seen == [False]
    assert output.read_bytes() == container
    assert output.stat().st_mode & 0o777 == 0o600
    assert sorted(tmp_path.iterdir()) == [output]


def test_a_file_that_appears_during_the_backup_is_never_replaced(ada, tmp_path, monkeypatch):
    output = tmp_path / "raced.dbs"
    real = backup_engine._verify_after_write

    def race(container, passphrase, payload_sha):
        real(container, passphrase, payload_sha)
        output.write_bytes(b"someone else")

    monkeypatch.setattr(backup_engine, "_verify_after_write", race)

    with pytest.raises(BackupError):
        create_backup(PASS, kdf_params=FAST_KDF, output=str(output))

    assert output.read_bytes() == b"someone else"
    assert sorted(tmp_path.iterdir()) == [output]


def test_a_filesystem_without_hard_links_still_gets_a_verified_private_file(
    ada, tmp_path, monkeypatch
):
    output = tmp_path / "no-links.dbs"

    def refuse(source, destination):
        raise OSError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(os, "link", refuse)

    container = create_backup(PASS, kdf_params=FAST_KDF, output=str(output))

    assert output.read_bytes() == container
    assert output.stat().st_mode & 0o777 == 0o600
    assert sorted(tmp_path.iterdir()) == [output]
    assert validate_backup(output.read_bytes(), PASS).ok


def test_skipping_verification_still_never_replaces_a_file(ada, tmp_path):
    output = tmp_path / "unverified.dbs"
    output.write_bytes(b"keep")

    with pytest.raises(BackupError):
        create_backup(PASS, kdf_params=FAST_KDF, output=str(output), verify=False)

    assert output.read_bytes() == b"keep"


@pytest.mark.parametrize("command", [("dbs_backup",), ("dbs", "backup")])
def test_the_command_refuses_an_existing_path_and_names_it(ada, tmp_path, command):
    output = tmp_path / "taken.dbs"
    output.write_bytes(b"keep")

    with pytest.raises(CommandError) as refused:
        call_command(*command, str(output), passphrase=PASS, stdout=StringIO(), **FAST)

    assert str(output) in str(refused.value)
    assert "already exists" in str(refused.value)
    assert output.read_bytes() == b"keep"
