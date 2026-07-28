"""Retention: what gets deleted, and everything that must never be deleted."""

import datetime

import pytest

from dbs.exceptions import ConfigurationError
from dbs.naming import backup_filename
from dbs.retention import prune_directory, prune_remote, stale_backups

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
