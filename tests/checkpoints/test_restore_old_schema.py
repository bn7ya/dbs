"""Restoring a checkpoint brings back the tables, rows and migration records it was taken from."""

from __future__ import annotations

import shutil
from decimal import Decimal

import pytest

from tests.checkpoints.harness import STAGES, VENDOR

AT_STAGE_ONE = ["0001_initial"]
AT_STAGE_TWO = ["0001_initial", "0002_account_currency"]
AT_STAGE_THREE = [*AT_STAGE_TWO, "0003_fill_currency"]


def entries(project) -> list:
    rows = project.query("SELECT id, amount, note FROM ledger_entry ORDER BY id")
    return [(pk, Decimal(str(amount)).quantize(Decimal("0.01")), note) for pk, amount, note in rows]


def restored(project, checkpoint, *options) -> None:
    project.manage("dbs", "restore", str(checkpoint), "--flush", *options)


@pytest.fixture
def migrated(shop):
    shop.migrate_to("2", "3", "4", "5")
    return shop


def test_the_faulty_migration_really_damaged_the_rows(migrated):
    assert migrated.query("SELECT amount_cents FROM ledger_entry ORDER BY id") == [[125], [999]]
    assert "amount" not in migrated.columns("ledger_entry")


def test_a_checkpoint_from_two_migrations_back_brings_back_its_schema_rows_and_records(migrated):
    two_back = migrated.checkpoint("before-migrate", "ledger.0004_owner_memo_receipt")

    restored(migrated, two_back)

    assert migrated.applied() == AT_STAGE_THREE
    assert sorted(migrated.columns("ledger_entry")) == ["account_id", "amount", "id", "note"]
    assert "owner_id" not in migrated.columns("ledger_account")
    assert "ledger_receipt" not in migrated.tables()
    assert entries(migrated) == [
        (1, Decimal("12.50"), "first"),
        (2, Decimal("99.99"), "second"),
    ]
    assert migrated.query("SELECT name, currency FROM ledger_account ORDER BY id") == [
        ["Cash", "USD"],
        ["Bank", "USD"],
    ]


def test_a_checkpoint_from_three_migrations_back_brings_back_its_schema_rows_and_records(
    migrated,
):
    three_back = migrated.checkpoint("before-migrate", "ledger.0003_fill_currency")

    restored(migrated, three_back)

    assert migrated.applied() == AT_STAGE_TWO
    assert sorted(migrated.columns("ledger_account")) == ["currency", "id", "name", "opened"]
    assert migrated.query("SELECT name, currency FROM ledger_account ORDER BY id") == [
        ["Cash", ""],
        ["Bank", ""],
    ]
    assert entries(migrated)[0] == (1, Decimal("12.50"), "first")
    assert migrated.query(
        "SELECT entry_id, tag_id FROM ledger_entry_tags ORDER BY entry_id, tag_id"
    ) == [[1, 1], [1, 2]]
    assert migrated.query("SELECT username FROM auth_user") == [["ada"]]


def test_the_oldest_checkpoint_goes_back_before_a_column_existed(migrated):
    oldest = migrated.checkpoint("before-migrate", "ledger.0002_account_currency")

    restored(migrated, oldest)

    assert migrated.applied() == AT_STAGE_ONE
    assert sorted(migrated.columns("ledger_account")) == ["id", "name", "opened"]


def test_the_migrations_apply_again_after_going_back(migrated):
    restored(migrated, migrated.checkpoint("before-migrate", "ledger.0003_fill_currency"))

    forward = migrated.at("4").manage("migrate", "--noinput")

    assert "Applying ledger.0003_fill_currency... OK" in forward.out
    assert "Applying ledger.0004_owner_memo_receipt... OK" in forward.out
    assert migrated.applied()[-1] == "0004_owner_memo_receipt"
    assert sorted(migrated.columns("ledger_entry")) == ["account_id", "amount", "id", "memo"]
    assert migrated.query("SELECT currency FROM ledger_account ORDER BY id") == [["USD"], ["USD"]]
    migrated.run(
        "from ledger.models import Account, Entry\n"
        "Entry.objects.create(account=Account.objects.first(), amount='1.00', memo='new')"
    )
    assert len(entries_with_memo(migrated)) == 3


def entries_with_memo(project) -> list:
    return project.query("SELECT id, memo FROM ledger_entry ORDER BY id")


def test_an_after_checkpoint_goes_forward_to_the_state_it_was_taken_in(migrated):
    restored(migrated, migrated.checkpoint("before-migrate", "ledger.0002_account_currency"))

    restored(migrated, migrated.checkpoint("after-migrate", "ledger.0004_owner_memo_receipt"))

    assert migrated.applied()[-1] == "0004_owner_memo_receipt"
    assert "ledger_receipt" in migrated.tables()
    assert sorted(migrated.columns("ledger_entry")) == ["account_id", "amount", "id", "memo"]


def test_rows_written_since_the_checkpoint_are_gone_and_new_rows_get_new_keys(migrated):
    migrated.run(
        "from ledger.models import Account, Entry\n"
        "Entry.objects.create(account=Account.objects.first(), amount_cents=5, memo='late')"
    )

    restored(migrated, migrated.checkpoint("before-migrate", "ledger.0005_amount_in_cents"))
    migrated.at("4").run(
        "from ledger.models import Account, Entry\n"
        "Entry.objects.create(account=Account.objects.first(), amount='3.00', memo='after')"
    )

    assert entries_with_memo(migrated) == [[1, "first"], [2, "second"], [3, "after"]]


def test_a_dry_run_says_what_would_change_and_changes_nothing(migrated):
    checkpoint = migrated.checkpoint("before-migrate", "ledger.0003_fill_currency")
    before = (migrated.applied(), migrated.tables(), migrated.checkpoints())

    rehearsed = migrated.manage("dbs", "restore", str(checkpoint), "--flush", "--dry-run")

    assert "tables would be rebuilt" in rehearsed.out
    assert (
        "No longer applied (3): ledger.0003_fill_currency, ledger.0004_owner_memo_receipt, "
        "ledger.0005_amount_in_cents"
    ) in rehearsed.out
    assert "nothing was written" in rehearsed.out
    assert (migrated.applied(), migrated.tables(), migrated.checkpoints()) == before


def test_a_checkpoint_is_not_restored_without_saying_the_tables_are_replaced(migrated):
    checkpoint = migrated.checkpoint("before-migrate", "ledger.0003_fill_currency")

    refused = migrated.manage("dbs", "restore", str(checkpoint), check=False)
    rehearsed = migrated.manage("dbs", "restore", str(checkpoint), "--dry-run", check=False)

    assert refused.code != 0 and rehearsed.code != 0
    assert "This is a checkpoint" in refused.err
    assert "--flush" in refused.err and "--no-schema" in refused.err
    assert migrated.applied()[-1] == "0005_amount_in_cents"
    assert not [name for name in migrated.checkpoints() if "-restore-" in name]


def test_a_migration_that_was_removed_since_stops_the_restore(migrated):
    checkpoint = migrated.checkpoint("before-migrate", "ledger.0005_amount_in_cents")
    (migrated.root / "ledger" / "migrations" / "0004_owner_memo_receipt.py").unlink()
    (migrated.root / "ledger" / "migrations" / "0005_amount_in_cents.py").unlink()

    refused = migrated.manage("dbs", "restore", str(checkpoint), "--flush", check=False)

    assert refused.code != 0
    assert "migrations this project no longer has: ledger.0004_owner_memo_receipt" in refused.err
    assert "amount_cents" in migrated.columns("ledger_entry")


def test_a_migration_that_was_edited_since_stops_the_restore(migrated):
    checkpoint = migrated.checkpoint("before-migrate", "ledger.0003_fill_currency")
    edited = migrated.root / "ledger" / "migrations" / "0002_account_currency.py"
    edited.write_text(edited.read_text().replace("max_length=3", "max_length=3, null=True"))

    refused = migrated.manage("dbs", "restore", str(checkpoint), "--flush", check=False)

    assert refused.code != 0
    assert "one of them was edited since" in refused.err
    assert migrated.applied()[-1] == "0005_amount_in_cents"


def test_a_model_left_out_of_backups_keeps_its_rows_when_its_table_did_not_change(shop):
    shop.options["PROJECT_EXCLUDE_MODELS"] = "ledger.tag"
    shop.migrate_to("2", "3")
    shop.run("from ledger.models import Tag\nTag.objects.create(label='late')")

    restored(shop, shop.checkpoint("before-migrate", "ledger.0002_account_currency"))

    assert shop.applied() == AT_STAGE_ONE
    assert shop.query("SELECT label FROM ledger_tag ORDER BY id") == [["rent"], ["food"], ["late"]]


def test_a_model_left_out_of_backups_whose_table_changed_stops_the_restore(shop):
    shop.options["PROJECT_EXCLUDE_MODELS"] = "ledger.account"
    shop.migrate_to("2")

    refused = shop.manage(
        "dbs", "restore", str(shop.checkpoint("before-migrate")), "--flush", check=False
    )

    assert refused.code != 0
    assert "holds no rows of ledger.account" in refused.err
    assert shop.applied() == AT_STAGE_TWO


def test_no_schema_loads_a_checkpoints_rows_into_the_tables_as_they_are(shop):
    shop.migrate_to("2")
    checkpoint = shop.checkpoint("after-migrate")
    shop.run("from ledger.models import Account\nAccount.objects.filter(name='Cash').update(name='Petty')")

    shop.manage("dbs", "restore", str(checkpoint), "--no-schema")

    assert shop.applied() == AT_STAGE_TWO
    assert shop.query("SELECT name FROM ledger_account ORDER BY id") == [["Cash"], ["Bank"]]


def test_an_ordinary_backup_is_not_asked_for_its_schema(shop, tmp_path):
    backup = tmp_path / "ordinary.dbs"
    shop.manage("dbs", "backup", str(backup))
    shop.migrate_to("2")

    shop.manage("dbs", "restore", str(backup), "--flush")

    assert shop.applied() == AT_STAGE_TWO
    assert "currency" in shop.columns("ledger_account")


def test_what_dbs_keeps_for_itself_is_not_rolled_back(migrated):
    events = migrated.query("SELECT COUNT(*) FROM dbs_auditevent")[0][0]
    records = migrated.query("SELECT COUNT(*) FROM dbs_backuprecord")[0][0]

    restored(migrated, migrated.checkpoint("before-migrate", "ledger.0002_account_currency"))

    assert migrated.query("SELECT COUNT(*) FROM dbs_auditevent")[0][0] > events
    assert migrated.query("SELECT COUNT(*) FROM dbs_backuprecord")[0][0] > records
    assert migrated.applied("dbs")[-1] == "0006_max_backups"
    assert "The audit trail is intact" in migrated.manage("dbs", "audit").out


def test_a_user_added_since_the_checkpoint_leaves_the_audit_trail_whole(migrated):
    migrated.run(
        "from django.contrib.auth import get_user_model\n"
        "from dbs import audit\n"
        "late = get_user_model().objects.create_superuser('late', password='correct-horse')\n"
        "audit.record('backup.validate', actor=late, target='x.dbs', data={'ok': True})"
    )

    restored(migrated, migrated.checkpoint("before-migrate", "ledger.0003_fill_currency"))

    assert migrated.query("SELECT username FROM auth_user") == [["ada"]]
    assert migrated.query(
        "SELECT actor_id FROM dbs_auditevent WHERE action = 'backup.validate' AND target_name = 'x.dbs'"
    ) == [[None]]
    assert "The audit trail is intact" in migrated.manage("dbs", "audit").out


@pytest.mark.skipif(VENDOR == "sqlite", reason="SQLite keeps foreign keys in the table itself.")
def test_foreign_keys_from_tables_left_alone_are_there_again(migrated):
    restored(migrated, migrated.checkpoint("before-migrate", "ledger.0003_fill_currency"))

    refused = migrated.python(
        "-c",
        "import django; django.setup()\n"
        "from django.db import connection\n"
        "cursor = connection.cursor()\n"
        "cursor.execute('UPDATE dbs_auditevent SET actor_id = 987654')",
        check=False,
    )

    assert refused.code != 0
    assert "foreign key" in refused.err.lower()


def test_raw_sql_a_migration_ran_is_named_because_it_is_not_repeated(shop):
    shop.at("2")
    raw = shop.root / "ledger" / "migrations" / "0003_index.py"
    shutil.copy(STAGES / "3" / "migrations" / "0003_fill_currency.py", raw)
    raw.write_text(
        "from django.db import migrations\n\n\n"
        "class Migration(migrations.Migration):\n"
        "    dependencies = [('ledger', '0002_account_currency')]\n\n"
        "    operations = [migrations.RunSQL(\n"
        "        'CREATE INDEX ledger_note ON ledger_entry (note)', 'DROP INDEX ledger_note'\n"
        "    )]\n"
    )
    shop.manage("migrate", "--noinput")
    after = shop.checkpoint("after-migrate", "ledger.0003_index")

    restoring = shop.manage("dbs", "restore", str(after), "--flush")

    assert "ran raw SQL, which rebuilding the tables does not repeat: ledger.0003_index" in restoring.out
