"""Integration test for the management commands (backup -> restore -> validate)."""

from io import StringIO

import pytest
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError

from tests.testapp.models import Author, Book, Tag

PASS = "cli-pass-phrase"


@pytest.mark.django_db
def test_cli_backup_restore_validate(tmp_path):
    author = Author.objects.create(name="Grace")
    tag = Tag.objects.create(label="cli")
    book = Book.objects.create(title="Command Line", author=author)
    book.tags.set([tag])
    book.cover.save("cli-cover.bin", ContentFile(b"CLI-COVER"), save=True)

    backup_file = tmp_path / "out.dbs"

    out = StringIO()
    call_command(
        "dbs_backup", str(backup_file),
        passphrase=PASS, kdf_time=1, kdf_memory=8192, stdout=out,
    )
    assert backup_file.exists() and "verified" in out.getvalue()

    # Structural validation needs no passphrase.
    vout = StringIO()
    call_command("dbs_validate", str(backup_file), stdout=vout)
    assert "VALID" in vout.getvalue()

    Book.objects.all().delete()
    Tag.objects.all().delete()
    Author.objects.all().delete()

    rout = StringIO()
    call_command("dbs_restore", str(backup_file), passphrase=PASS, stdout=rout)
    assert "Restored" in rout.getvalue()
    assert Book.objects.get(title="Command Line").author.name == "Grace"


@pytest.mark.django_db
def test_passphrase_can_arrive_on_stdin(tmp_path, monkeypatch):
    Author.objects.create(name="Hopper")
    backup_file = tmp_path / "stdin.dbs"

    monkeypatch.setattr("sys.stdin", StringIO(f"{PASS}\n"))
    call_command(
        "dbs_backup", str(backup_file),
        passphrase_stdin=True, kdf_time=1, kdf_memory=8192, stdout=StringIO(),
    )
    assert backup_file.exists()

    Author.objects.all().delete()

    monkeypatch.setattr("sys.stdin", StringIO(f"{PASS}\n"))
    call_command(
        "dbs_restore", str(backup_file), passphrase_stdin=True, stdout=StringIO()
    )
    assert Author.objects.filter(name="Hopper").exists()


@pytest.mark.django_db
def test_restore_dry_run_reports_and_changes_nothing(tmp_path):
    Author.objects.create(name="Preview")
    backup_file = tmp_path / "dry.dbs"
    call_command(
        "dbs_backup", str(backup_file),
        passphrase=PASS, kdf_time=1, kdf_memory=8192, stdout=StringIO(),
    )
    Author.objects.all().delete()

    out = StringIO()
    call_command(
        "dbs_restore", str(backup_file), passphrase=PASS, dry_run=True, stdout=out
    )
    text = out.getvalue()
    assert "Dry run" in text
    assert "nothing was written" in text
    assert not Author.objects.exists()


@pytest.mark.django_db
def test_restore_flush_replaces_existing_rows(tmp_path):
    Author.objects.create(name="Original")
    backup_file = tmp_path / "flush.dbs"
    call_command(
        "dbs_backup", str(backup_file),
        passphrase=PASS, kdf_time=1, kdf_memory=8192, stdout=StringIO(),
    )
    Author.objects.create(name="Added Later")

    out = StringIO()
    call_command(
        "dbs_restore", str(backup_file), passphrase=PASS, flush=True, stdout=out
    )
    text = out.getvalue()
    assert "Flushed" in text
    assert "Restored" in text
    assert not Author.objects.filter(name="Added Later").exists()
    assert Author.objects.filter(name="Original").exists()


@pytest.mark.django_db
def test_an_empty_stdin_passphrase_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdin", StringIO(""))
    with pytest.raises(CommandError):
        call_command(
            "dbs_backup", str(tmp_path / "no.dbs"),
            passphrase_stdin=True, kdf_time=1, kdf_memory=8192, stdout=StringIO(),
        )
