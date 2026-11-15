"""manage.py migrate keeps a backup of the database before and after what it applies."""

from __future__ import annotations

import pytest

from tests.checkpoints.harness import VENDOR


def test_the_first_migration_of_an_empty_database_keeps_no_checkpoint(shop):
    assert shop.checkpoints() == []


def test_a_migration_is_kept_between_a_checkpoint_before_it_and_one_after(shop):
    ran = shop.at("2").manage("migrate", "--noinput")

    before, after = shop.listed()
    assert (before["role"], after["role"]) == ("before-migrate", "after-migrate")
    assert before["migrations"] == after["migrations"] == ["ledger.0002_account_currency"]
    assert before["name"].startswith("shop-before-migrate-")
    assert after["name"].startswith("shop-after-migrate-")
    assert f"Checkpoint before this migration: {before['path']}" in ran.out
    assert f"Checkpoint after this migration: {after['path']}" in ran.out
    assert ran.out.index("Checkpoint before") < ran.out.index("Applying ledger.0002")
    assert ran.out.index("Applying ledger.0002") < ran.out.index("Checkpoint after")


def test_a_checkpoint_says_what_it_is_when_validated(shop):
    shop.at("2").manage("migrate", "--noinput")

    before = shop.manage("dbs", "validate", str(shop.checkpoint("before-migrate")), "--passphrase")

    assert "[VALID]" in before.out
    assert "Application: shop" in before.out
    assert "Checkpoint before a migrate (ledger.0002_account_currency)" in before.out


def test_nothing_to_apply_keeps_no_checkpoint(shop):
    shop.manage("migrate", "--noinput")
    shop.manage("migrate", "--plan")
    shop.manage("migrate", "--check")

    assert shop.checkpoints() == []


def test_several_migrations_in_one_run_share_one_pair(shop):
    shop.at("4").manage("migrate", "--noinput")

    before, after = shop.listed()
    assert before["migrations"] == [
        "ledger.0002_account_currency",
        "ledger.0003_fill_currency",
        "ledger.0004_owner_memo_receipt",
    ]
    assert after["role"] == "after-migrate"


def test_migrating_backwards_is_kept_between_checkpoints_too(shop):
    shop.at("2").manage("migrate", "--noinput")

    shop.manage("migrate", "ledger", "0001", "--noinput")

    assert shop.roles() == ["before-migrate", "after-migrate"] * 2
    assert shop.listed()[-1]["migrations"] == ["-ledger.0002_account_currency"]


def test_a_failed_migration_keeps_the_checkpoint_before_it_and_says_how_to_put_it_back(shop):
    shop.at("4").manage("migrate", "--noinput")

    failed = shop.at("broken").manage("migrate", "--noinput", check=False)

    kept = shop.checkpoint("before-migrate", "ledger.0005_checked")
    assert failed.code != 0
    assert "this migration is broken" in failed.err
    assert shop.roles() == ["before-migrate", "after-migrate", "before-migrate"]
    assert f'python manage.py dbs restore "{kept}" --flush' in failed.err

    shop.manage("dbs", "restore", str(kept), "--flush")

    assert "checked" not in shop.columns("ledger_entry")
    assert shop.applied()[-1] == "0004_owner_memo_receipt"
    assert shop.at("4").manage("migrate", "--check", check=False).code == 0


def test_no_checkpoint_migrates_without_one(shop):
    ran = shop.at("2").manage("migrate", "--noinput", "--no-checkpoint")

    assert shop.checkpoints() == []
    assert "Checkpoint" not in ran.text
    assert shop.applied()[-1] == "0002_account_currency"


def test_the_setting_switches_checkpoints_off(shop):
    shop.options["PROJECT_CHECKPOINTS"] = "off"

    ran = shop.at("2").manage("migrate", "--noinput")

    assert shop.checkpoints() == []
    assert "Checkpoint" not in ran.text


def test_a_project_without_a_backup_folder_migrates_as_before_and_is_told(make_project):
    project = make_project(backups=False)
    project.at("1").manage("migrate", "--noinput")

    ran = project.at("2").manage("migrate", "--noinput")

    assert "DBS keeps no checkpoint here: DBS_BACKUP_DIR is not set" in ran.out
    assert project.applied()[-1] == "0002_account_currency"
    assert project.at("2").manage("migrate", "--noinput", "-v", "0").out == ""


def test_a_checkpoint_that_cannot_be_written_stops_the_migration(shop, tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("not a folder")
    shop.backups = blocker / "backups"

    refused = shop.at("2").manage("migrate", "--noinput", check=False)

    assert refused.code != 0
    assert "the migration did not start" in refused.err
    assert "--no-checkpoint" in refused.err
    assert shop.applied() == ["0001_initial"]
    assert "currency" not in shop.columns("ledger_account")


def test_older_checkpoints_go_once_there_are_more_than_the_limit(shop):
    shop.options["PROJECT_MAX_BACKUPS"] = 3

    shop.migrate_to("2", "3", "4")

    listed = shop.listed()
    assert [entry["role"] for entry in listed] == ["after-migrate", "before-migrate", "after-migrate"]
    assert listed[0]["migrations"] == ["ledger.0003_fill_currency"]
    assert listed[-1]["migrations"] == ["ledger.0004_owner_memo_receipt"]


def test_the_newest_pair_stays_even_under_a_limit_of_one(shop):
    shop.options["PROJECT_MAX_BACKUPS"] = 1

    shop.migrate_to("2", "3")

    listed = shop.listed()
    assert [entry["role"] for entry in listed] == ["before-migrate", "after-migrate"]
    assert {tuple(entry["migrations"]) for entry in listed} == {("ledger.0003_fill_currency",)}


def test_checkpoints_never_remove_a_backup_that_is_not_one(shop):
    shop.options["PROJECT_MAX_BACKUPS"] = 1
    shop.backups.mkdir()
    for number in range(3):
        shop.manage(
            "dbs", "backup", str(shop.backups / f"shop-2026010{number + 1}-020000Z.dbs"),
            "--passphrase", "a-manual-backup",
        )

    shop.migrate_to("2", "3")

    kept = shop.checkpoints()
    assert len([name for name in kept if "-migrate-" not in name]) == 3
    assert len([name for name in kept if "-migrate-" in name]) == 2


def test_the_list_of_checkpoints_reads_as_text_and_as_json(shop):
    empty = shop.manage("dbs", "checkpoints")
    shop.at("2").manage("migrate", "--noinput")

    listed = shop.manage("dbs", "checkpoints")

    assert "No checkpoints in" in empty.out
    assert "before a migrate: ledger.0002_account_currency" in listed.out
    assert "after a migrate: ledger.0002_account_currency" in listed.out
    assert "manage.py dbs restore PATH --flush" in listed.out
    assert {entry["database"] for entry in shop.listed()} == {"default"}
    assert all(entry["size"] > 0 for entry in shop.listed())


def test_a_migration_of_dbs_alone_keeps_no_checkpoint(shop):
    shop.manage("migrate", "dbs", "0005", "--noinput")

    shop.manage("migrate", "dbs", "--noinput")

    assert shop.checkpoints() == []


@pytest.mark.skipif(VENDOR != "sqlite", reason="A file path names a SQLite database.")
def test_a_test_database_keeps_no_checkpoint(shop):
    shop.database.settings["NAME"] = shop.database.settings["NAME"].replace("dbs_cp_", "test_")
    shop.at("1").manage("migrate", "--noinput")

    shop.at("2").manage("migrate", "--noinput")

    assert shop.checkpoints() == []
