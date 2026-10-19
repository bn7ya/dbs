from __future__ import annotations

from types import SimpleNamespace

import pytest

from dbs.manager.applications.paths import host_path, on_host

MOUNTS = [
    {"type": "bind", "source": "/srv/shop", "destination": "/app", "rw": True},
    {
        "type": "bind",
        "source": "/srv/shop-media",
        "destination": "/app/media",
        "rw": True,
    },
    {
        "type": "volume",
        "source": "/var/lib/docker/volumes/static/_data",
        "destination": "/app/static/",
        "rw": False,
    },
]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/app", "/srv/shop"),
        ("/app/.env", "/srv/shop/.env"),
        ("/app/media", "/srv/shop-media"),
        ("/app/media/avatars/1.png", "/srv/shop-media/avatars/1.png"),
        ("/app/static/css", "/var/lib/docker/volumes/static/_data/css"),
        ("/app/static", "/var/lib/docker/volumes/static/_data"),
        ("/application", None),
        ("/app2/media", None),
        ("/etc/passwd", None),
    ],
)
def test_a_container_path_is_found_on_the_host_through_the_deepest_mount(
    path, expected
):
    assert on_host(MOUNTS, path) == expected


def test_a_mount_of_the_whole_filesystem_maps_every_path():
    mounts = [{"type": "bind", "source": "/srv/root", "destination": "/"}]

    assert on_host(mounts, "/etc/app.env") == "/srv/root/etc/app.env"
    assert on_host(mounts, "/") == "/srv/root"


def test_a_mount_without_a_source_maps_nothing():
    mounts = [{"type": "tmpfs", "source": "", "destination": "/app/tmp"}]

    assert on_host(mounts, "/app/tmp/x") is None


@pytest.mark.parametrize("mounts", [[], None])
def test_without_mounts_nothing_is_on_the_host(mounts):
    assert on_host(mounts, "/app/.env") is None


def test_an_application_on_the_host_keeps_its_paths():
    application = SimpleNamespace(in_container=False, mounts=MOUNTS)

    assert host_path(application, "/app/.env") == "/app/.env"
    assert host_path(application, "") is None


def test_an_application_in_a_container_maps_its_paths_or_has_none_on_the_host():
    application = SimpleNamespace(in_container=True, mounts=MOUNTS)

    assert host_path(application, "/app/media/a.png") == "/srv/shop-media/a.png"
    assert host_path(application, "/var/backups/dbs") is None
    assert host_path(application, "") is None
