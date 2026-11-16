"""manage.py makemigrations makes sure DBS can keep a checkpoint of the migration it writes."""

from __future__ import annotations


def written(project) -> list:
    return sorted(path.name for path in (project.root / "ledger" / "migrations").glob("0*.py"))


def pending(shop):
    shop.migrate_to("4")
    (shop.root / "ledger" / "models.py").write_text(
        (shop.root / "ledger" / "models.py").read_text()
        + "    printed = models.BooleanField(default=False)\n"
    )
    return shop


def test_a_ready_project_writes_its_migration(shop):
    project = pending(shop)

    made = project.manage("makemigrations", "ledger")

    assert "Add field printed to receipt" in made.out
    assert len(written(project)) == 5
    assert "DBS" not in made.out


def test_a_backup_folder_that_cannot_be_written_stops_makemigrations(shop, tmp_path):
    project = pending(shop)
    blocker = tmp_path / "a-file"
    blocker.write_text("not a folder")
    project.backups = blocker / "backups"

    refused = project.manage("makemigrations", "ledger", check=False)

    assert refused.code != 0
    assert "DBS is not ready to keep a checkpoint of the next migration" in refused.err
    assert "no migration was written" in refused.err
    assert "is not a folder this process can write into" in refused.err
    assert "--no-checkpoint" in refused.err
    assert len(written(project)) == 4


def test_a_project_with_no_passphrase_stops_makemigrations(shop):
    project = pending(shop)

    refused = project.manage("makemigrations", "ledger", check=False, PROJECT_SECRET_KEY="")

    assert refused.code != 0
    assert "no passphrase encrypts a checkpoint" in refused.err or "SECRET_KEY" in refused.err
    assert len(written(project)) == 4


def test_checking_and_rehearsing_are_never_stopped(shop, tmp_path):
    project = pending(shop)
    blocker = tmp_path / "a-file"
    blocker.write_text("not a folder")
    project.backups = blocker / "backups"

    checked = project.manage("makemigrations", "--check", check=False)
    rehearsed = project.manage("makemigrations", "ledger", "--dry-run")

    assert "DBS is not ready" not in checked.text
    assert "Add field printed to receipt" in rehearsed.out
    assert len(written(project)) == 4


def test_no_checkpoint_and_the_setting_let_makemigrations_through(shop, tmp_path):
    project = pending(shop)
    blocker = tmp_path / "a-file"
    blocker.write_text("not a folder")
    project.backups = blocker / "backups"

    project.manage("makemigrations", "ledger", "--no-checkpoint")
    first = written(project)
    (project.root / "ledger" / "migrations" / first[-1]).unlink()
    project.manage("makemigrations", "ledger", PROJECT_CHECKPOINTS="off")

    assert len(first) == len(written(project)) == 5


def test_without_a_backup_folder_makemigrations_writes_and_says_no_checkpoint_follows(
    make_project,
):
    project = make_project(backups=False)
    project.at("1").manage("migrate", "--noinput")
    project.at("2")
    (project.root / "ledger" / "migrations" / "0002_account_currency.py").unlink()

    made = project.manage("makemigrations", "ledger")

    assert "DBS will keep no checkpoint of the next migration: DBS_BACKUP_DIR is not set." in made.out
    assert len(written(project)) == 2
