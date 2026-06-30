"""Integration test for the management commands (backup -> restore -> validate)."""

from io import StringIO

import pytest
from django.core.files.base import ContentFile
from django.core.management import call_command

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
