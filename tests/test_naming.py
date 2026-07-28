"""Backup filename convention: build, parse, match, order."""

import datetime

import pytest

from dbs.naming import (
    backup_filename,
    backup_prefix,
    is_backup_name,
    parse_backup_moment,
    sorted_backups,
)

MOMENT = datetime.datetime(2026, 7, 28, 2, 0, 0, tzinfo=datetime.timezone.utc)


def test_filename_is_utc_and_round_trips():
    name = backup_filename(moment=MOMENT)
    assert name == "backup-20260728-020000Z.dbs"
    assert parse_backup_moment(name) == MOMENT


def test_local_moment_is_normalised_to_utc():
    plus_four = datetime.timezone(datetime.timedelta(hours=4))
    local = MOMENT.astimezone(plus_four)
    assert backup_filename(moment=local) == backup_filename(moment=MOMENT)


def test_ordinal_disambiguates_same_second():
    first = backup_filename(moment=MOMENT)
    second = backup_filename(moment=MOMENT, ordinal=2)
    assert first != second
    assert parse_backup_moment(second) == MOMENT
    assert backup_prefix(second) == "backup"


def test_lexicographic_order_matches_chronological_order():
    moments = [
        MOMENT,
        MOMENT + datetime.timedelta(seconds=1),
        MOMENT + datetime.timedelta(days=400),
    ]
    names = [backup_filename(moment=moment) for moment in moments]
    assert sorted(names) == names


def test_prefix_matching():
    name = backup_filename("prod", moment=MOMENT)
    assert name.startswith("prod-")
    assert is_backup_name(name)
    assert is_backup_name(name, "prod")
    assert not is_backup_name(name, "staging")
    assert backup_prefix(name) == "prod"


@pytest.mark.parametrize(
    "name",
    [
        "notes.txt",
        "backup.dbs",
        "backup-20260728.dbs",
        "backup-20260728-020000.dbs",
        "backup-20260728-020000Z.tar",
        "backup-20261301-020000Z.dbs",
    ],
)
def test_foreign_names_never_match(name):
    assert parse_backup_moment(name) is None
    assert not is_backup_name(name)


def test_sorted_backups_filters_and_orders():
    older = backup_filename("prod", moment=MOMENT)
    newer = backup_filename("prod", moment=MOMENT + datetime.timedelta(hours=1))
    other = backup_filename("staging", moment=MOMENT)
    names = [newer, "README.md", other, older]

    assert sorted_backups(names, "prod") == [older, newer]
    assert sorted_backups(names) == [older, other, newer]
