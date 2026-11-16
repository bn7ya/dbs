"""A restore is kept between a checkpoint before it and one after, like a migration."""

from __future__ import annotations


def accounts(project) -> list:
    return [name for (name,) in project.query("SELECT name FROM ledger_account ORDER BY id")]


def backed_up(project, tmp_path):
    backup = tmp_path / "ordinary.dbs"
    project.manage("dbs", "backup", str(backup))
    return backup


def test_a_restore_is_kept_between_a_checkpoint_before_it_and_one_after(shop, tmp_path):
    backup = backed_up(shop, tmp_path)
    shop.run("from ledger.models import Account\nAccount.objects.create(name='Late')")

    restoring = shop.manage("dbs", "restore", str(backup), "--flush")

    before, after = shop.listed()
    assert (before["role"], after["role"]) == ("before-restore", "after-restore")
    assert f"Checkpoint before this restore: {before['path']}" in restoring.out
    assert f"Checkpoint after this restore: {after['path']}" in restoring.out
    assert "Restored" in restoring.out
    assert accounts(shop) == ["Cash", "Bank"]


def test_the_checkpoint_before_a_restore_brings_back_what_the_restore_replaced(shop, tmp_path):
    backup = backed_up(shop, tmp_path)
    shop.run("from ledger.models import Account\nAccount.objects.create(name='Late')")
    shop.manage("dbs", "restore", str(backup), "--flush")

    shop.manage("dbs", "restore", str(shop.checkpoint("before-restore")), "--flush")

    assert accounts(shop) == ["Cash", "Bank", "Late"]
    assert shop.roles() == ["before-restore", "after-restore"] * 2


def test_a_dry_run_keeps_no_checkpoint(shop, tmp_path):
    backup = backed_up(shop, tmp_path)

    shop.manage("dbs", "restore", str(backup), "--dry-run")
    shop.manage("dbs", "restore", str(backup), "--no-data")

    assert shop.checkpoints() == []


def test_no_checkpoint_restores_without_one(shop, tmp_path):
    backup = backed_up(shop, tmp_path)

    restoring = shop.manage("dbs", "restore", str(backup), "--flush", "--no-checkpoint")

    assert shop.checkpoints() == []
    assert "Checkpoint" not in restoring.text


def test_the_setting_switches_restore_checkpoints_off_too(shop, tmp_path):
    backup = backed_up(shop, tmp_path)
    shop.options["PROJECT_CHECKPOINTS"] = "off"

    shop.manage("dbs", "restore", str(backup))

    assert shop.checkpoints() == []


def test_a_restore_that_is_refused_keeps_no_checkpoint(shop, tmp_path):
    backup = backed_up(shop, tmp_path)

    wrong = shop.manage(
        "dbs", "restore", str(backup), "--passphrase", "not-the-passphrase", check=False
    )
    foreign = shop.manage("dbs", "restore", str(backup), check=False, PROJECT_APPLICATION="depot")

    assert wrong.code != 0 and foreign.code != 0
    assert "belongs to the application 'shop'" in foreign.err
    assert shop.checkpoints() == []


def test_a_checkpoint_that_cannot_be_written_stops_the_restore(shop, tmp_path):
    backup = backed_up(shop, tmp_path)
    shop.run("from ledger.models import Account\nAccount.objects.create(name='Late')")
    blocker = tmp_path / "a-file"
    blocker.write_text("not a folder")
    shop.backups = blocker / "backups"

    refused = shop.manage("dbs", "restore", str(backup), "--flush", check=False)

    assert refused.code != 0
    assert "the restore did not start" in refused.err and "--no-checkpoint" in refused.err
    assert accounts(shop) == ["Cash", "Bank", "Late"]


def test_restoring_a_checkpoint_does_not_prune_the_checkpoint_being_restored(shop):
    shop.options["PROJECT_MAX_BACKUPS"] = 1
    shop.migrate_to("2")
    oldest = shop.checkpoint("before-migrate")

    shop.manage("dbs", "restore", str(oldest), "--flush")

    assert oldest.name in shop.checkpoints()
    assert shop.applied() == ["0001_initial"]


def test_a_restore_into_a_database_that_was_never_migrated_keeps_no_checkpoint(
    shop, make_project, tmp_path
):
    backup = backed_up(shop, tmp_path)
    fresh = make_project(folder="fresh")
    fresh.at("1").manage("migrate", "--noinput", "--no-checkpoint")

    fresh.manage("dbs", "restore", str(backup))

    assert accounts(fresh) == ["Cash", "Bank"]
    assert [entry["role"] for entry in fresh.listed()] == ["before-restore", "after-restore"]
