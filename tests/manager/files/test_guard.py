from __future__ import annotations

from datetime import datetime
from datetime import timezone as dt_timezone

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from dbs.manager.files.exceptions import CannotDeleteRoot, PathOutsideRoots
from dbs.manager.files.serializers import ENTRY_KINDS
from dbs.manager.files.services import FileService
from dbs.manager.servers.exceptions import RemoteNotFound
from dbs.manager.servers.gateways import EntryKind, RemoteEntry
from dbs.manager.servers.services import ServerService
from tests.manager.servers.support import PASSWORD, connecting_to

CONNECT = "dbs.manager.servers.services.connection_service.connect"
MEDIA = "/srv/app/media"
DATA = "/data/media"


class Answering:
    def __init__(
        self, real: dict[str, str], kinds: dict[str, str] | None = None
    ) -> None:
        self.real = real
        self.kinds = kinds or {}
        self.asked: list[str] = []
        self.done: list[tuple] = []

    def realpath(self, path: str) -> str:
        self.asked.append(path)
        if path not in self.real:
            raise RemoteNotFound()
        return self.real[path]

    def lstat(self, path: str) -> RemoteEntry:
        return self.entry(path, self.kinds.get(path, EntryKind.FILE))

    def listdir(self, folder: str) -> list[RemoteEntry]:
        self.done.append(("listdir", folder))
        return [
            self.entry(f"{folder}/b.txt", EntryKind.FILE),
            self.entry(f"{folder}/A", "folder"),
        ]

    def write_new(self, source, folder: str, name: str) -> RemoteEntry:
        self.done.append(("write_new", folder, name))
        return self.entry(f"{folder}/{name}", EntryKind.FILE)

    def make_folder(self, path: str) -> RemoteEntry:
        self.done.append(("make_folder", path))
        return self.entry(path, EntryKind.FOLDER)

    def remove_file(self, path: str) -> None:
        self.done.append(("remove_file", path))

    def remove_empty_folder(self, path: str) -> None:
        self.done.append(("remove_empty_folder", path))

    @staticmethod
    def entry(path: str, kind: str) -> RemoteEntry:
        return RemoteEntry(
            name=path.rsplit("/", 1)[-1],
            path=path,
            kind=kind,
            size=1 if kind == EntryKind.FILE else None,
            mtime=datetime(2026, 10, 1, tzinfo=dt_timezone.utc),
            permissions=0o644,
        )


@pytest.fixture
def media_server(admin, server):
    return ServerService(admin).update(
        server.pk, account_password=PASSWORD, file_roots=[MEDIA]
    )


@pytest.fixture
def answering(monkeypatch):
    def answer(real: dict[str, str], kinds: dict[str, str] | None = None) -> Answering:
        remote = Answering(real, kinds)
        monkeypatch.setattr(CONNECT, connecting_to(remote))
        return remote

    return answer


def test_the_api_names_every_kind_the_gateway_tells_apart():
    assert list(EntryKind.ALL) == ENTRY_KINDS


@pytest.mark.django_db
def test_a_link_the_server_resolves_out_of_the_allowed_folder_is_refused_for_everything(
    admin, media_server, answering
):
    remote = answering({MEDIA: MEDIA, f"{MEDIA}/link": "/etc"})
    files = FileService(admin)

    attempts = [
        lambda: files.list(media_server.pk, f"{MEDIA}/link"),
        lambda: files.download(media_server.pk, f"{MEDIA}/link"),
        lambda: files.create_folder(media_server.pk, f"{MEDIA}/link", "planted"),
        lambda: files.upload(
            media_server.pk, f"{MEDIA}/link", SimpleUploadedFile("x", b"x")
        ),
    ]
    for attempt in attempts:
        with pytest.raises(PathOutsideRoots):
            attempt()

    assert remote.done == []


@pytest.mark.django_db
def test_each_root_is_resolved_once_per_request(admin, server, tree, answering):
    real = {root: root for root in tree.roots} | {
        f"{tree.media}/Docs": f"{tree.media}/Docs"
    }
    remote = answering(real)

    FileService(admin).list(server.pk, f"{tree.media}/Docs")

    assert remote.asked == [*tree.roots, f"{tree.media}/Docs"]


@pytest.mark.django_db
def test_a_root_the_server_cannot_resolve_allows_nothing(
    admin, media_server, answering
):
    remote = answering({f"{MEDIA}/x": f"{MEDIA}/x"})

    with pytest.raises(PathOutsideRoots):
        FileService(admin).list(media_server.pk, f"{MEDIA}/x")

    assert remote.done == []


@pytest.mark.django_db
@pytest.mark.parametrize("answer", ["media/x", "", f"{MEDIA}/../../etc", f"{MEDIA}2"])
def test_an_answer_that_is_not_a_path_in_a_root_is_refused(
    admin, media_server, answering, answer
):
    remote = answering({MEDIA: MEDIA, f"{MEDIA}/x": answer})

    with pytest.raises(PathOutsideRoots):
        FileService(admin).list(media_server.pk, f"{MEDIA}/x")

    assert remote.done == []


@pytest.mark.django_db
def test_paths_are_checked_against_where_the_roots_really_are(
    admin, media_server, answering
):
    remote = answering(
        {MEDIA: DATA, f"{MEDIA}/a": f"{DATA}/a", f"{MEDIA}/b": f"{MEDIA}/b"}
    )
    files = FileService(admin)

    folder = files.list(media_server.pk, f"{MEDIA}/a")
    with pytest.raises(PathOutsideRoots):
        files.list(media_server.pk, f"{MEDIA}/b")

    assert remote.done == [("listdir", f"{DATA}/a")]
    assert (folder.path, folder.parent, folder.root) == (f"{MEDIA}/a", MEDIA, MEDIA)
    assert [(entry.name, entry.path) for entry in folder.entries] == [
        ("A", f"{MEDIA}/a/A"),
        ("b.txt", f"{MEDIA}/a/b.txt"),
    ]


@pytest.mark.django_db
def test_a_new_entry_is_made_in_the_real_folder_and_answered_by_the_typed_one(
    admin, media_server, answering
):
    remote = answering({MEDIA: DATA, f"{MEDIA}/sub": f"{DATA}/sub"})
    files = FileService(admin)

    uploaded = files.upload(
        media_server.pk, f"{MEDIA}/sub", SimpleUploadedFile("a.txt", b"x")
    )
    made = files.create_folder(media_server.pk, f"{MEDIA}/sub", "photos")

    assert remote.done == [
        ("write_new", f"{DATA}/sub", "a.txt"),
        ("make_folder", f"{DATA}/sub/photos"),
    ]
    assert (uploaded.path, made.path) == (f"{MEDIA}/sub/a.txt", f"{MEDIA}/sub/photos")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("kind", "done"),
    [
        (EntryKind.LINK, "remove_file"),
        (EntryKind.FILE, "remove_file"),
        (EntryKind.OTHER, "remove_file"),
        (EntryKind.FOLDER, "remove_empty_folder"),
    ],
)
def test_a_delete_acts_on_the_entry_itself_through_its_real_folder(
    admin, media_server, answering, kind, done
):
    remote = answering({MEDIA: DATA}, kinds={f"{DATA}/entry": kind})

    FileService(admin).delete(media_server.pk, f"{MEDIA}/entry")

    assert remote.done == [(done, f"{DATA}/entry")]
    assert f"{MEDIA}/entry" not in remote.asked


@pytest.mark.django_db
def test_an_entry_that_is_a_root_where_the_server_resolves_it_is_never_deleted(
    admin, server, answering
):
    ServerService(admin).update(
        server.pk, account_password=PASSWORD, file_roots=[MEDIA, "/srv/shared"]
    )
    remote = answering({MEDIA: MEDIA, "/srv/shared": f"{MEDIA}/shared"})

    with pytest.raises(CannotDeleteRoot):
        FileService(admin).delete(server.pk, f"{MEDIA}/shared")

    assert remote.done == []


@pytest.mark.django_db
def test_an_upload_closes_its_file_whatever_happens(admin, media_server, answering):
    answering({MEDIA: MEDIA, f"{MEDIA}/link": "/etc"})
    refused = SimpleUploadedFile("a.txt", b"x")
    kept = SimpleUploadedFile("a.txt", b"x")

    with pytest.raises(PathOutsideRoots):
        FileService(admin).upload(media_server.pk, f"{MEDIA}/link", refused)
    FileService(admin).upload(media_server.pk, MEDIA, kept)

    assert refused.closed and kept.closed
