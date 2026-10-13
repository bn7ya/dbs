"""Retention: what gets deleted, and everything that must never be deleted."""

import datetime

import pytest

from dbs.exceptions import ConfigurationError
from dbs.naming import backup_filename
from dbs.retention import (
    FAILED,
    PASSED,
    UNKNOWN,
    StoredBackup,
    current_backup_names,
    prune_directory,
    prune_remote,
    read_created,
    server_keep,
    stale_backups,
    stale_stored_backups,
    sweep_leftovers,
)

MOMENT = datetime.datetime(2026, 7, 28, 2, 0, 0, tzinfo=datetime.timezone.utc)


def names_for(count, prefix="backup"):
    return [
        backup_filename(prefix, moment=MOMENT + datetime.timedelta(hours=hour))
        for hour in range(count)
    ]


class FakeSession:
    def __init__(self, names):
        self._names = list(names)
        self.deleted = []

    def names(self):
        return list(self._names)

    def delete(self, name):
        self._names.remove(name)
        self.deleted.append(name)


def test_keeps_the_newest_and_drops_the_oldest():
    names = names_for(5)
    assert stale_backups(names, keep=2) == names[:3]


def test_nothing_stale_when_under_the_limit():
    assert stale_backups(names_for(2), keep=5) == []


def test_foreign_and_other_prefix_names_are_never_candidates():
    names = names_for(3, "prod") + names_for(3, "staging") + ["important.sql", "README"]
    stale = stale_backups(names, keep=1, prefix="prod")
    assert stale == names_for(3, "prod")[:2]


def test_keep_below_one_is_refused():
    for keep in (0, -1):
        with pytest.raises(ConfigurationError):
            stale_backups(names_for(3), keep=keep)


def test_prune_directory_removes_only_stale_files(tmp_path):
    names = names_for(4)
    for name in names + ["keep-me.sql"]:
        (tmp_path / name).write_bytes(b"x")

    removed = prune_directory(str(tmp_path), keep=2)

    assert removed == names[:2]
    survivors = sorted(path.name for path in tmp_path.iterdir())
    assert survivors == sorted(names[2:] + ["keep-me.sql"])


def test_prune_directory_dry_run_deletes_nothing(tmp_path):
    names = names_for(3)
    for name in names:
        (tmp_path / name).write_bytes(b"x")

    assert prune_directory(str(tmp_path), keep=1, dry_run=True) == names[:2]
    assert len(list(tmp_path.iterdir())) == 3


def test_prune_directory_tolerates_a_missing_directory(tmp_path):
    assert prune_directory(str(tmp_path / "absent"), keep=1) == []


def test_prune_remote_deletes_through_the_session():
    names = names_for(4)
    session = FakeSession(names + ["unrelated.txt"])

    removed = prune_remote(session, keep=1)

    assert removed == names[:3]
    assert session.deleted == names[:3]
    assert "unrelated.txt" in session.names()


def test_prune_remote_dry_run_deletes_nothing():
    session = FakeSession(names_for(3))
    assert prune_remote(session, keep=1, dry_run=True) == names_for(3)[:2]
    assert session.deleted == []


NOW = MOMENT + datetime.timedelta(days=1)


def stored(name_hour, *, recorded_hour=None, verification=UNKNOWN):
    name = backup_filename(moment=MOMENT + datetime.timedelta(hours=name_hour))
    hour = name_hour if recorded_hour is None else recorded_hour
    return StoredBackup(name, MOMENT + datetime.timedelta(hours=hour), verification)


def test_a_name_stamped_in_the_future_is_never_counted_or_pruned():
    names = names_for(3)
    future = backup_filename(moment=NOW + datetime.timedelta(days=3650))

    assert stale_backups(names + [future], keep=1, now=NOW) == names[:2]
    assert stale_backups([future], keep=1, now=NOW) == []
    assert future not in current_backup_names(names + [future], now=NOW)


def test_the_recorded_time_orders_backups_not_the_name():
    renamed = stored(0, recorded_hour=10)
    middle = stored(5)
    newest = stored(8)

    assert stale_stored_backups([renamed, middle, newest], keep=2) == [middle.name]


def test_a_backup_that_failed_verification_never_takes_a_place():
    good = [stored(hour, verification=PASSED) for hour in range(3)]
    broken = stored(5, verification=FAILED)

    assert stale_stored_backups(good + [broken], keep=3) == []
    assert stale_stored_backups(good + [broken], keep=2) == [good[0].name]


def test_a_failed_backup_goes_once_enough_newer_files_exist():
    broken = stored(0, verification=FAILED)
    newer = [stored(hour, verification=PASSED) for hour in range(1, 4)]

    assert stale_stored_backups([broken] + newer[:1], keep=2) == []
    assert stale_stored_backups([broken] + newer, keep=2) == [broken.name, newer[0].name]


def test_the_newest_verified_backup_is_never_pruned():
    verified = stored(0, verification=PASSED)
    unverified = [stored(hour) for hour in range(1, 4)]

    stale = stale_stored_backups([verified] + unverified, keep=2)

    assert verified.name not in stale
    assert stale == [unverified[0].name]


def test_retention_always_keeps_one():
    with pytest.raises(ConfigurationError):
        stale_stored_backups([stored(0)], keep=0)
    assert stale_stored_backups([stored(0, verification=FAILED)], keep=1) == []


@pytest.mark.parametrize("keep", [1, 5, "3"])
def test_the_server_keeps_between_one_and_five(keep):
    assert server_keep(keep) == int(keep)


@pytest.mark.parametrize("keep", [0, 6, 14, -1, "many", None])
def test_the_server_refuses_to_keep_more_than_five(keep):
    with pytest.raises(ConfigurationError) as excinfo:
        server_keep(keep)

    assert "at most 5" in str(excinfo.value)


def test_the_manifest_carries_the_time_a_backup_was_taken(tmp_path):
    from dbs.container.format import write_container

    taken = MOMENT + datetime.timedelta(minutes=7)
    path = tmp_path / "taken.dbs"
    manifest = {"created": taken.isoformat(), "blocks": {"block_size": 1024}, "copy_len": 0}
    path.write_bytes(write_container(manifest, b"", b"", flags=0))
    (tmp_path / "junk.dbs").write_bytes(b"not a container")
    (tmp_path / "empty.dbs").write_bytes(b"")

    assert read_created(str(path)) == (True, taken)
    assert read_created(str(tmp_path / "junk.dbs")) == (False, None)
    assert read_created(str(tmp_path / "empty.dbs")) == (False, None)


def test_leftovers_older_than_an_hour_are_swept_and_nothing_else(tmp_path):
    import os
    import time

    real = names_for(1)[0]
    stale_partial = f".{real}.ab12cd34"
    fresh_partial = f".{names_for(2)[1]}.zz99yy88"
    stale_reservation = names_for(3)[2]
    hidden_backup = ".hand-kept.dbs"
    for name in (real, hidden_backup):
        (tmp_path / name).write_bytes(b"DBSCON01 backup bytes")
    for name in (stale_partial, fresh_partial):
        (tmp_path / name).write_bytes(b"partial")
    (tmp_path / stale_reservation).write_bytes(b"")
    hour_ago = time.time() - 2 * 3600
    for name in (real, hidden_backup, stale_partial, stale_reservation):
        os.utime(tmp_path / name, (hour_ago, hour_ago))

    removed = sweep_leftovers(str(tmp_path))

    assert sorted(removed) == sorted([stale_partial, stale_reservation])
    survivors = {path.name for path in tmp_path.iterdir()}
    assert survivors == {real, hidden_backup, fresh_partial}
