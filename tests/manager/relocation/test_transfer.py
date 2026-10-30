from __future__ import annotations

from dataclasses import replace

import pytest

from dbs.manager.relocation import catalogue
from dbs.manager.relocation.exceptions import (
    TargetFileExists,
    TargetFolderNotEmpty,
    TransferDigestMismatch,
)
from dbs.manager.relocation.privileged import Privileged
from dbs.manager.relocation.transfer import FILE, FOLDER, IMAGE, VOLUME, Carrier, Item
from dbs.manager.servers.gateways import RemoteHost
from tests.manager.relocation.hosts import LocalSource, LocalTarget
from tests.manager.remote import ScriptedSession


@pytest.fixture
def world(tmp_path):
    project = tmp_path / "source" / "srv" / "shop"
    (project / ".git").mkdir(parents=True)
    (project / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (project / "manage.py").write_text("print('hi')\n")
    (project / "db.sqlite3").write_text("live data\n")
    (project / ".env").write_text("SECRET_KEY=x\n")
    staging = tmp_path / "target" / "home" / "deploy" / ".dbs-staging" / "relocation-1"
    source = LocalSource()
    target = LocalTarget()
    target.root = str(tmp_path / "target")
    source_session = ScriptedSession(
        "10.0.0.5", {("tar",): source, ("docker",): source, ("sudo",): source}
    )
    target_session = ScriptedSession(
        "10.0.0.6",
        {("sudo",): target, ("sha256sum",): target, ("docker",): target, ("podman",): target},
    )
    carrier = Carrier(
        source=Privileged(RemoteHost(source_session), catalogue.NOPASSWD),
        target=Privileged(RemoteHost(target_session), catalogue.NOPASSWD),
        spool=tmp_path / "manager" / "relocation" / "1",
        staging=str(staging),
        source_ids=("1001", "1001"),
        target_ids=("1000", "1000"),
    )
    return {
        "root": tmp_path,
        "project": project,
        "target_folder": tmp_path / "target" / "srv" / "shop",
        "staging": staging,
        "source": source,
        "target": target,
        "carrier": carrier,
    }


def folder_item(world, excludes=("db.sqlite3",)):
    return Item(
        key="folder",
        kind=FOLDER,
        read=catalogue.tar_create(str(world["project"]), excludes),
        target=str(world["target_folder"]),
        numeric=False,
    )


def test_a_folder_arrives_whole_with_its_git_and_without_what_was_left_out(world):
    outcome = world["carrier"].carry(folder_item(world))

    landed = world["target_folder"]
    assert (landed / ".git" / "HEAD").read_text() == "ref: refs/heads/main\n"
    assert (landed / "manage.py").exists() and (landed / ".env").exists()
    assert not (landed / "db.sqlite3").exists()
    assert outcome["placed"] == str(landed) and len(outcome["sha256"]) == 64
    assert list(world["staging"].iterdir()) == []
    assert list((world["root"] / "manager" / "relocation" / "1").iterdir()) == []
    assert world["carrier"].leftovers == []


def test_the_sources_user_becomes_the_targets_user(world):
    world["carrier"].carry(folder_item(world))

    chowns = [run["argv"] for run in world["target"].ran if run["argv"][0] == "chown"]
    assert [argv[3:5] for argv in chowns] == [["--from=1001", "1000"], ["--from=:1001", ":1000"]]
    assert all(run["sudo"] for run in world["target"].ran if run["argv"][0] == "chown")


def test_the_folder_itself_takes_the_owner_and_mode_it_had_on_the_source(world):
    world["carrier"].carry(replace(folder_item(world), owner=("1001", "1001", "750")))

    ran = [run["argv"] for run in world["target"].ran if run["argv"][0] in ("chown", "chmod")]
    assert [argv[:3] for argv in ran] == [
        ["chown", "-h", "1001:1001"],
        ["chmod", "750", "--"],
        ["chown", "-R", "-h"],
        ["chown", "-R", "-h"],
    ]
    assert ".shop.dbs-incoming-" in ran[0][-1]
    assert world["target_folder"].stat().st_mode & 0o777 == 0o750


def test_a_folder_that_already_holds_something_is_never_written_over(world):
    world["target_folder"].mkdir(parents=True)
    (world["target_folder"] / "keep.txt").write_text("mine\n")

    with pytest.raises(TargetFolderNotEmpty):
        world["carrier"].carry(folder_item(world))

    assert (world["target_folder"] / "keep.txt").read_text() == "mine\n"
    assert not (world["target_folder"] / "manage.py").exists()
    [leftover] = world["carrier"].leftovers
    assert ".shop.dbs-incoming-" in leftover


def test_an_empty_folder_waiting_on_the_target_is_used(world):
    world["target_folder"].mkdir(parents=True)

    world["carrier"].carry(folder_item(world))

    assert (world["target_folder"] / "manage.py").exists()


def test_a_digest_that_does_not_match_is_sent_again(world):
    world["target"].digest_fails = 1

    world["carrier"].carry(folder_item(world))

    assert (world["target_folder"] / "manage.py").exists()


def test_a_digest_that_never_matches_stops_the_move(world):
    world["target"].digest_fails = 10

    with pytest.raises(TransferDigestMismatch):
        world["carrier"].carry(folder_item(world))

    assert not world["target_folder"].exists()
    assert list(world["staging"].iterdir()) == []


def test_a_file_outside_the_folder_is_placed_where_nothing_is(world):
    outside = world["root"] / "source" / "etc"
    outside.mkdir(parents=True)
    (outside / "shop.env").write_text("DEBUG=0\n")
    destination = world["root"] / "target" / "etc" / "shop.env"
    item = Item(
        key="file:/etc/shop.env",
        kind=FILE,
        read=catalogue.tar_create_member(str(outside), "shop.env"),
        target=str(destination),
    )

    world["carrier"].carry(item)

    assert destination.read_text() == "DEBUG=0\n"
    assert [path.name for path in destination.parent.iterdir()] == ["shop.env"]
    with pytest.raises(TargetFileExists):
        world["carrier"].carry(item)


def test_an_image_is_saved_loaded_and_checked(world):
    item = Item(
        key="image:shop-web",
        kind=IMAGE,
        read=catalogue.image_save("docker", "shop-web:latest"),
        target="shop-web:latest",
        engine="docker",
        expected_id="sha256:abc",
    )

    outcome = world["carrier"].carry(item)

    assert world["target"].loaded == [b"IMAGE:shop-web:latest"]
    assert outcome["loaded"] == "shop-web:latest" and "warning" not in outcome


def test_an_image_whose_id_changed_is_noted(world):
    world["target"].image_id = "sha256:other"
    item = Item(
        key="image:shop-web",
        kind=IMAGE,
        read=catalogue.image_save("docker", "shop-web:latest"),
        target="shop-web:latest",
        engine="docker",
        expected_id="sha256:abc",
    )

    assert world["carrier"].carry(item)["warning"] == "image_id_changed"


def test_a_volume_is_made_with_its_compose_labels_and_filled(world):
    data = world["root"] / "source" / "volumes" / "shop_media"
    data.mkdir(parents=True)
    (data / "logo.png").write_bytes(b"\x89PNG")
    item = Item(
        key="volume:shop_media",
        kind=VOLUME,
        read=catalogue.tar_create(str(data), root=True),
        target="shop_media",
        engine="docker",
        labels=(("com.docker.compose.project", "shop"), ("com.docker.compose.volume", "media")),
    )

    world["carrier"].carry(item)

    assert (world["target"].volumes["shop_media"] / "logo.png").read_bytes() == b"\x89PNG"
    [create] = [run["argv"] for run in world["target"].ran if run["argv"][1:3] == ["volume", "create"]]
    assert create == [
        "docker",
        "volume",
        "create",
        "--label",
        "com.docker.compose.project=shop",
        "--label",
        "com.docker.compose.volume=media",
        "shop_media",
    ]
    assert world["source"].reads[-1][:2] == ["tar", "--create"]


def test_nothing_on_the_source_but_reads(world):
    world["carrier"].carry(folder_item(world))

    for argv in world["source"].reads:
        assert argv[:2] == ["tar", "--create"] or argv[1:2] == ["save"]
