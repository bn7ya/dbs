"""The instructions DBS ships so an AI assistant knows how to use it."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from dbs.management.commands.dbs_ai import ASSETS, SKILL_DIR, shipped_files


def test_the_assets_ship_with_the_package():
    assert (ASSETS / "SKILL.md").is_file()
    assert (ASSETS / "AGENTS.md").is_file()
    assert (ASSETS / "llms.txt").is_file()
    assert sorted(path.name for path in (ASSETS / "reference").glob("*.md")) == [
        "commands.md",
        "security.md",
        "settings.md",
        "transports.md",
    ]


def test_the_skill_carries_usable_frontmatter():
    text = (ASSETS / "SKILL.md").read_text()
    lines = text.splitlines()

    assert lines[0] == "---"
    assert any(line.startswith("name: django-dbs") for line in lines[:5])
    description = next(line for line in lines if line.startswith("description:"))
    assert len(description) > 60
    assert "---" in lines[1:6]


def test_the_skill_covers_what_loses_data():
    text = (ASSETS / "SKILL.md").read_text()

    assert "SECRET_KEY_FALLBACKS" in text
    assert "--dry-run" in text
    assert "--flush" in text
    assert "DBS_ADMIN_CONSOLE_SHELL" in text


def test_the_skill_tells_assistants_to_keep_projects_current():
    text = (ASSETS / "SKILL.md").read_text()

    assert "dbs upgrade --check" in text
    assert "Never confirm the abandonment of backups" in text


def test_every_assistant_facing_file_carries_the_backup_prohibition():
    for name in ("SKILL.md", "AGENTS.md", "llms.txt"):
        text = (ASSETS / name).read_text().lower()
        assert "abandon" in text, name
        assert "dbs upgrade" in text, name


def test_install_writes_the_skill_into_a_project(tmp_path):
    out = StringIO()

    call_command("dbs", "ai", root=str(tmp_path), stdout=out)

    for relative in shipped_files():
        assert (tmp_path / relative).is_file(), relative
    assert str(tmp_path / SKILL_DIR) in out.getvalue()


def test_check_passes_after_an_install_and_fails_after_drift(tmp_path):
    call_command("dbs", "ai", root=str(tmp_path), stdout=StringIO())
    out = StringIO()

    call_command("dbs", "ai", check=True, root=str(tmp_path), stdout=out)
    assert "current" in out.getvalue()

    (tmp_path / SKILL_DIR / "SKILL.md").write_text("edited by hand")
    with pytest.raises(CommandError):
        call_command("dbs", "ai", check=True, root=str(tmp_path), stdout=StringIO())


def test_check_fails_when_nothing_is_installed(tmp_path):
    with pytest.raises(CommandError):
        call_command("dbs", "ai", check=True, root=str(tmp_path), stdout=StringIO())


def test_agents_appends_once_and_leaves_existing_content_alone(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# House rules\n\nBe kind.\n")

    call_command("dbs", "ai", agents=True, root=str(tmp_path), stdout=StringIO())
    after_first = (tmp_path / "AGENTS.md").read_text()

    call_command("dbs", "ai", agents=True, root=str(tmp_path), stdout=StringIO())

    assert "Be kind." in after_first
    assert "## django-dbs" in after_first
    assert after_first == (tmp_path / "AGENTS.md").read_text()
    assert after_first.count("## django-dbs") == 1


def test_agents_creates_the_file_when_there_is_none(tmp_path):
    call_command("dbs", "ai", agents=True, root=str(tmp_path), stdout=StringIO())

    assert (tmp_path / "AGENTS.md").read_text().startswith("## django-dbs")


def test_print_writes_the_skill_to_stdout_without_touching_disk(tmp_path):
    out = StringIO()

    call_command("dbs", "ai", print_only=True, root=str(tmp_path), stdout=out)

    assert "name: django-dbs" in out.getvalue()
    assert not (tmp_path / ".claude").exists()
