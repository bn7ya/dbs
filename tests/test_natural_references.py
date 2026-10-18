import logging

import pytest
from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType

from dbs import serialize
from dbs.engine import create_backup, restore_backup
from tests.payloads import read_payload
from dbs.exceptions import RestoreError
from dbs.registry import BackupRegistry
from tests.conftest import FAST_KDF
from tests.testapp.models import Author, Book, Bookmark

PASS = "natural-references-pass-phrase"


def _registry(*models):
    registry = BackupRegistry()
    for model in models:
        registry.register(model)
    return registry


def _records(container, label):
    return [record for record in read_payload(container, PASS).records if record["model"] == label]


def _renumber_permission(permission):
    old_pk = permission.pk
    permission.delete()
    moved = Permission.objects.create(
        codename=permission.codename,
        name=permission.name,
        content_type=permission.content_type,
    )
    Permission.objects.create(
        pk=old_pk,
        codename=f"impostor_{old_pk}",
        name="Impostor",
        content_type=ContentType.objects.get_for_model(Author),
    )
    return moved


def _renumber_content_type(model):
    current = ContentType.objects.get_for_model(model)
    old_pk = current.pk
    current.delete()
    ContentType.objects.clear_cache()
    moved = ContentType.objects.create(app_label=current.app_label, model=current.model)
    ContentType.objects.create(pk=old_pk, app_label="testapp", model="impostor")
    ContentType.objects.clear_cache()
    return moved


@pytest.fixture(autouse=True)
def fresh_content_type_cache():
    ContentType.objects.clear_cache()
    yield
    ContentType.objects.clear_cache()


@pytest.fixture
def editors(db):
    add_book = Permission.objects.get(codename="add_book")
    view_author = Permission.objects.get(codename="view_author")
    group = Group.objects.create(name="editors")
    group.permissions.set([add_book])
    ada = User.objects.create_user("ada")
    ada.groups.add(group)
    ada.user_permissions.set([view_author])
    return {"add_book": add_book, "view_author": view_author}


def test_permissions_are_written_by_natural_key(editors):
    container = create_backup(PASS, registry=_registry(Group, User), kdf_params=FAST_KDF)

    group = _records(container, "auth.group")[0]
    user = _records(container, "auth.user")[0]
    assert group["fields"]["permissions"] == [["add_book", "testapp", "book"]]
    assert user["fields"]["user_permissions"] == [["view_author", "testapp", "author"]]
    assert user["fields"]["groups"] == [group["pk"]]


def test_permissions_restore_onto_their_own_rows_when_ids_differ(editors):
    container = create_backup(PASS, registry=_registry(Group, User), kdf_params=FAST_KDF)
    User.objects.all().delete()
    Group.objects.all().delete()
    _renumber_permission(editors["add_book"])
    _renumber_permission(editors["view_author"])

    restore_backup(container, PASS)

    group = Group.objects.get(name="editors")
    ada = User.objects.get(username="ada")
    assert list(group.permissions.values_list("codename", flat=True)) == ["add_book"]
    assert list(ada.user_permissions.values_list("codename", flat=True)) == ["view_author"]
    assert ada.has_perm("testapp.add_book")
    assert ada.has_perm("testapp.view_author")


@pytest.mark.parametrize("flush", [False, True])
def test_content_type_references_restore_by_natural_key(db, flush):
    author = Author.objects.create(name="Ada")
    Bookmark.objects.create(
        content_type=ContentType.objects.get_for_model(Author), object_id=author.pk, note="first"
    )
    container = create_backup(PASS, registry=_registry(Author, Bookmark), kdf_params=FAST_KDF)
    assert _records(container, "testapp.bookmark")[0]["fields"]["content_type"] == [
        "testapp",
        "author",
    ]
    Bookmark.objects.all().delete()
    moved = _renumber_content_type(Author)

    restore_backup(container, PASS, flush=flush)

    bookmark = Bookmark.objects.get()
    assert bookmark.content_type_id == moved.pk
    assert bookmark.target == author


def test_a_permission_the_target_lacks_is_dropped_with_a_warning(editors, caplog):
    book = ContentType.objects.get_for_model(Book)
    retired = Permission.objects.create(codename="archive_book", name="Can archive", content_type=book)
    Group.objects.get(name="editors").permissions.add(retired)
    container = create_backup(PASS, registry=_registry(Group, User), kdf_params=FAST_KDF)
    User.objects.all().delete()
    Group.objects.all().delete()
    retired.delete()

    with caplog.at_level(logging.WARNING, logger="dbs"):
        restore_backup(container, PASS)

    group = Group.objects.get(name="editors")
    assert list(group.permissions.values_list("codename", flat=True)) == ["add_book"]
    assert "archive_book" in caplog.text


def test_a_foreign_key_the_target_cannot_resolve_stops_the_restore(db):
    gone = ContentType.objects.create(app_label="retired", model="thing")
    Bookmark.objects.create(content_type=gone, object_id=1)
    container = create_backup(PASS, registry=_registry(Bookmark), kdf_params=FAST_KDF)
    Bookmark.objects.all().delete()
    gone.delete()

    with pytest.raises(RestoreError, match="retired.*thing"):
        restore_backup(container, PASS)
    assert not Bookmark.objects.exists()


def test_a_carried_model_keeps_primary_key_references(editors):
    container = create_backup(
        PASS, registry=_registry(Permission, Group, User), kdf_params=FAST_KDF
    )

    group = _records(container, "auth.group")[0]
    assert group["fields"]["permissions"] == [editors["add_book"].pk]


def test_an_older_backup_with_primary_key_references_still_restores(
    editors, monkeypatch, caplog
):
    monkeypatch.setattr(serialize.AllRowsSerializer, "by_natural_key", lambda self, model: False)
    container = create_backup(PASS, registry=_registry(Group, User), kdf_params=FAST_KDF)
    monkeypatch.undo()
    User.objects.all().delete()
    Group.objects.all().delete()

    with caplog.at_level(logging.WARNING, logger="dbs"):
        restore_backup(container, PASS)

    group = Group.objects.get(name="editors")
    assert list(group.permissions.values_list("codename", flat=True)) == ["add_book"]
    assert "auth.permission" in caplog.text
