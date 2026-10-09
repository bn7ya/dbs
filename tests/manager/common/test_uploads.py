from __future__ import annotations

import pytest

from dbs.manager.common.uploads import upload_name, utf8_length


@pytest.mark.parametrize(
    ("sent", "kept"),
    [
        ("db.sql.gz", "db.sql.gz"),
        ("/var/backups/db.sql.gz", "db.sql.gz"),
        ("D:\\dumps\\db.sql.gz", "db.sql.gz"),
        ("mixed/folders\\db.sql.gz", "db.sql.gz"),
        ("db\x00.sql.gz", "db.sql.gz"),
        ("tab\there.sql", "tabhere.sql"),
        (" \u00a0spaced\u2028.sql ", "spaced.sql"),
        ("\u202egpj.exe", "gpj.exe"),
        ("." * 3, "..."),
        ("x" * 255, "x" * 255),
        ("x" * 256, "x" * 255),
        ("x" * 300 + "." + "y" * 300, "." + "y" * 254),
    ],
)
def test_upload_name_keeps_what_follows_the_last_folder_printable_and_trimmed(
    sent, kept
):
    assert upload_name(sent, 255) == kept


@pytest.mark.parametrize(
    "sent", ["", " ", ".", "..", " . ", "backups/", "C:\\", "a/\x00", "\x1b"]
)
def test_upload_name_finds_nothing_in_a_name_of_only_folders_spaces_or_dots(sent):
    assert upload_name(sent, 255) is None


def test_a_name_measured_in_characters_keeps_them_all_however_many_bytes_they_take():
    arabic = "نسخة" * 60 + ".sql"

    assert upload_name(arabic, 255) == arabic


@pytest.mark.parametrize(
    ("sent", "kept"),
    [
        ("نسخة" * 60 + ".sql", "نسخة" * 31 + "ن" + ".sql"),
        ("ن" * 200, "ن" * 127),
        ("x" * 254 + "ن", "x" * 254),
        ("x" * 300 + ".نسخة", "x" * 246 + ".نسخة"),
    ],
    ids=[
        "arabic-with-extension",
        "arabic",
        "last-character-split",
        "latin-arabic-extension",
    ],
)
def test_a_name_measured_in_bytes_is_cut_where_a_character_ends(sent, kept):
    name = upload_name(sent, 255, utf8_length)

    assert name == kept
    assert utf8_length(name) <= 255
    name.encode().decode()


def test_a_name_that_fits_in_bytes_is_kept_whole():
    name = "ن" * 127 + "x"

    assert upload_name(name, 255, utf8_length) == name
