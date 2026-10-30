from __future__ import annotations

import json

import pytest

from dbs.manager.applications.services import facts
from dbs.manager.applications.services.discovery_service import answer_bonus


def test_database_facts_keep_typed_keys_and_never_a_password():
    stdout = "\n".join(
        [
            "Some startup noise",
            facts.FACTS_MARKER
            + json.dumps(
                {
                    "vendor": "postgresql",
                    "engine": "django.db.backends.postgresql",
                    "host": "db",
                    "port": "5432",
                    "name": "shop",
                    "user": "shop",
                    "password": "s3cret",
                    "caches": [
                        {"scheme": "redis", "host": "cache", "port": 6379, "password": "x"}
                    ],
                    "broker": {"scheme": "amqp", "host": "rabbit", "port": 99999},
                }
            ),
        ]
    )

    found = facts.parsed_database_facts(stdout)

    assert found == {
        "vendor": "postgresql",
        "engine": "django.db.backends.postgresql",
        "host": "db",
        "port": "5432",
        "name": "shop",
        "user": "shop",
        "caches": [{"scheme": "redis", "host": "cache", "port": 6379}],
        "broker": {"scheme": "amqp", "host": "rabbit", "port": None},
    }
    assert "s3cret" not in json.dumps(found)


@pytest.mark.parametrize("stdout", ["", "nothing here", facts.FACTS_MARKER + "[1, 2]"])
def test_database_facts_without_the_marker_are_unknown(stdout):
    assert facts.parsed_database_facts(stdout) is None


def test_the_facts_script_never_reads_the_database_password():
    assert "PASSWORD" not in facts.DATABASE_FACTS


@pytest.mark.parametrize(
    ("url", "kept", "stripped"),
    [
        ("https://token@github.com/org/shop.git", "https://github.com/org/shop.git", True),
        (
            "https://user:pass@git.example.com/shop.git",
            "https://git.example.com/shop.git",
            True,
        ),
        ("ssh://git@example.com/shop.git", "ssh://git@example.com/shop.git", False),
        ("ssh://git:pw@example.com/shop.git", "ssh://example.com/shop.git", True),
        ("git@github.com:org/shop.git", "git@github.com:org/shop.git", False),
        ("https://github.com/org/shop.git", "https://github.com/org/shop.git", False),
    ],
)
def test_git_remotes_lose_their_credentials(url, kept, stripped):
    assert facts.strip_credentials(url) == (kept, stripped)


def test_compose_services_and_what_builds_here_are_read():
    text = "\n".join(
        [
            "name: shop",
            "services:",
            "  web:",
            "    build: .",
            "    env_file: .env",
            "  db:",
            "    image: 'postgres:16'",
            "    volumes:",
            "      - data:/var/lib/postgresql/data",
            "volumes:",
            "  data:",
        ]
    )

    assert facts.services_of(text) == {
        "web": {"build": True, "image": ""},
        "db": {"build": False, "image": "postgres:16"},
    }


@pytest.mark.parametrize(
    ("database", "expected"),
    [
        ({"vendor": "sqlite", "host": ""}, "file"),
        ({"vendor": "postgresql", "host": ""}, "host_package"),
        ({"vendor": "postgresql", "host": "localhost"}, "host_package"),
        ({"vendor": "postgresql", "host": "/var/run/postgresql"}, "host_package"),
        ({"vendor": "postgresql", "host": "host.docker.internal"}, "host_package"),
        ({"vendor": "postgresql", "host": "db"}, "compose_service"),
        ({"vendor": "mysql", "host": "shop-mysql"}, "companion_container"),
        ({"vendor": "postgresql", "host": "db.example.net"}, "remote"),
        ({"vendor": "", "host": "db"}, ""),
        (None, ""),
    ],
)
def test_where_the_database_runs(database, expected):
    assert facts.placement(database, ["web", "db"], ["shop-mysql"]) == expected


def test_a_service_file_belongs_to_a_folder_it_names():
    assert facts.mentions("WorkingDirectory=/srv/shop\n", "/srv/shop")
    assert facts.mentions("root /srv/shop/static;", "/srv/shop/")
    assert not facts.mentions("WorkingDirectory=/srv/shopfront\n", "/srv/shop")


def test_services_for_leaves_out_the_text_and_other_folders():
    found = [
        {"kind": "unit", "scope": "system", "name": "shop.service", "path": "/etc/systemd/system/shop.service", "enabled": True, "text": "ExecStart=/srv/shop/.venv/bin/gunicorn"},
        {"kind": "site", "scope": "system", "name": "blog", "path": "/etc/nginx/sites-enabled/blog", "enabled": True, "text": "root /srv/blog;"},
    ]

    assert facts.services_for(found, "/srv/shop") == [
        {"kind": "unit", "scope": "system", "name": "shop.service", "path": "/etc/systemd/system/shop.service", "enabled": True}
    ]
    assert facts.services_for(found, "/") == []


def test_the_detected_profile_follows_what_was_found():
    candidate = {
        "kind": "host",
        "engine": "",
        "env": [{"path": "/srv/shop/.env", "location": "host", "source": "folder"}],
    }
    found = {
        "database": {"vendor": "postgresql"},
        "placement": "host_package",
        "git": {"head": "a" * 40},
        "services": [
            {"kind": "unit", "scope": "system"},
            {"kind": "site", "scope": "system"},
        ],
        "folder_read": True,
    }

    assert facts.detected_profile(candidate, found) == {
        "runs_in": "host",
        "database": "postgresql",
        "database_runs": "this_server",
        "settings_from": "folder_env",
        "source": "git",
        "process_manager": "systemd",
        "web_server": "nginx",
    }


@pytest.mark.parametrize(
    ("entries", "kind", "expected"),
    [
        ([{"source": "compose", "location": "host"}], "compose", "compose_env_file"),
        ([{"source": "dbs", "location": "container"}], "container", "image"),
        ([{"source": "folder", "location": "host"}], "host", "folder_env"),
        ([], "compose", "environment"),
        ([], "host", ""),
    ],
)
def test_where_settings_come_from(entries, kind, expected):
    assert facts.env_source({"kind": kind, "env": entries}) == expected


def test_answers_that_agree_with_what_was_found_rank_a_candidate_higher():
    detected = {"runs_in": "compose", "engine": "podman", "database": "mysql"}

    assert answer_bonus({"runs_in": "compose"}, detected) == 4
    assert answer_bonus({"runs_in": "compose", "engine": "podman", "database": "mariadb"}, detected) == 6
    assert answer_bonus({"runs_in": "host"}, detected) == 0
    assert answer_bonus({}, detected) == 0
