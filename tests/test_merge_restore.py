import pytest
from django.db import IntegrityError

from dbs import FieldType, ModelBackup
from dbs.engine import create_backup, restore_backup
from dbs.registry import BackupRegistry
from tests.conftest import FAST_KDF
from tests.format1 import as_format1
from tests.restoreapp.models import Account, Bar, Member, Place, Restaurant

PASS = "merge-restore-pass-phrase"


class SecretTokens(ModelBackup):
    overrides = {"api_token": FieldType.EXCLUDE}


class LocalNotes(ModelBackup):
    overrides = {"note": FieldType.EXCLUDE}


class TenantA(ModelBackup):
    def get_queryset(self, model):
        return model._base_manager.filter(tenant="a")


def _registry(config, *others):
    registry = BackupRegistry()
    registry.register(Member)
    registry.register(Account)(config)
    for model in others:
        registry.register(model)
    return registry


@pytest.mark.django_db
def test_a_merge_leaves_excluded_fields_of_existing_rows_alone():
    member = Member.objects.create(name="Ada")
    account = Account.objects.create(name="ops", tenant="a", api_token=7)
    account.members.set([member])
    registry = _registry(SecretTokens)
    container = create_backup(PASS, registry=registry, kdf_params=FAST_KDF)
    Account.objects.filter(pk=account.pk).update(name="renamed", api_token=99)
    account.members.clear()

    out = restore_backup(container, PASS, registry=registry)

    restored = Account.objects.get(pk=account.pk)
    assert restored.name == "ops"
    assert restored.api_token == 99
    assert list(restored.members.all()) == [member]
    assert out.records_loaded == 2


@pytest.mark.django_db
def test_rows_that_do_not_exist_yet_are_inserted_with_defaults_for_excluded_fields():
    account = Account.objects.create(name="ops", tenant="a", api_token=7, note="local")
    registry = _registry(LocalNotes)
    container = create_backup(PASS, registry=registry, kdf_params=FAST_KDF)
    Account.objects.all().delete()

    restore_backup(container, PASS, registry=registry)

    restored = Account.objects.get(pk=account.pk)
    assert restored.name == "ops"
    assert restored.api_token == 7
    assert restored.note == "fresh"


@pytest.mark.django_db
def test_a_merge_still_updates_every_field_the_backup_carries():
    account = Account.objects.create(name="ops", tenant="a", api_token=7, note="local")
    registry = _registry(ModelBackup)
    container = create_backup(PASS, registry=registry, kdf_params=FAST_KDF)
    Account.objects.filter(pk=account.pk).update(name="renamed", api_token=1, note="edited")

    restore_backup(container, PASS, registry=registry)

    restored = Account.objects.get(pk=account.pk)
    assert (restored.name, restored.api_token, restored.note) == ("ops", 7, "local")


@pytest.mark.django_db
def test_flush_deletes_only_the_rows_a_scoped_backup_covers():
    member = Member.objects.create(name="Ada")
    kept = Account.objects.create(name="a-1", tenant="a", api_token=1)
    other = Account.objects.create(name="b-1", tenant="b", api_token=2)
    other.members.set([member])
    registry = _registry(TenantA)
    container = create_backup(PASS, registry=registry, kdf_params=FAST_KDF)
    later = Account.objects.create(name="a-2", tenant="a", api_token=3)
    later.members.set([member])

    out = restore_backup(container, PASS, flush=True, registry=registry)

    assert Account.objects.filter(pk=kept.pk).exists()
    assert not Account.objects.filter(pk=later.pk).exists()
    assert Account.objects.filter(pk=other.pk).exists()
    assert list(Account.objects.get(pk=other.pk).members.all()) == [member]
    tenant_a_accounts, their_member_links, members = 2, 1, 1
    assert out.records_flushed == tenant_a_accounts + their_member_links + members


@pytest.mark.django_db
def test_a_dry_run_flush_counts_only_the_scoped_rows():
    Account.objects.create(name="a-1", tenant="a", api_token=1)
    Account.objects.create(name="b-1", tenant="b", api_token=2)
    Account.objects.create(name="b-2", tenant="b", api_token=3)
    registry = _registry(TenantA)
    container = create_backup(PASS, registry=registry, kdf_params=FAST_KDF)

    out = restore_backup(container, PASS, flush=True, dry_run=True, registry=registry)

    assert out.records_flushed == 1
    assert Account.objects.count() == 3


@pytest.mark.django_db
def test_flushing_a_child_only_backup_leaves_sibling_rows_alone():
    diner = Restaurant.objects.create(name="diner")
    registry = BackupRegistry()
    registry.register(Restaurant)
    container = create_backup(PASS, registry=registry, kdf_params=FAST_KDF)
    pub = Bar.objects.create(name="pub", taps=3)
    late = Restaurant.objects.create(name="late")

    restore_backup(container, PASS, flush=True, registry=registry)

    assert Bar.objects.get(pk=pub.pk).name == "pub"
    assert Restaurant.objects.get(pk=diner.pk).name == "diner"
    assert not Restaurant.objects.filter(pk=late.pk).exists()
    assert not Place.objects.filter(pk=late.pk).exists()


@pytest.mark.django_db
def test_flush_keeps_the_links_of_an_excluded_many_to_many():
    member = Member.objects.create(name="Ada")
    account = Account.objects.create(name="ops", tenant="a", api_token=1)
    account.members.set([member])

    class NoMembers(ModelBackup):
        overrides = {"members": FieldType.EXCLUDE}

    registry = BackupRegistry()
    registry.register(Account)(NoMembers)
    container = create_backup(PASS, registry=registry, kdf_params=FAST_KDF)

    restore_backup(container, PASS, flush=True, registry=registry)

    assert list(Account.objects.get(pk=account.pk).members.all()) == [member]


@pytest.mark.django_db
@pytest.mark.parametrize("form", [1, 2])
def test_a_flush_that_leaves_a_link_to_a_row_it_removed_is_refused(form):
    registry = BackupRegistry()
    registry.register(Member)
    container = create_backup(PASS, registry=registry, kdf_params=FAST_KDF)
    if form == 1:
        container = as_format1(container, PASS)
    member = Member.objects.create(name="Ada")
    account = Account.objects.create(name="ops", tenant="a", api_token=1)
    account.members.set([member])

    with pytest.raises(IntegrityError):
        restore_backup(container, PASS, flush=True, registry=registry)

    assert list(account.members.all()) == [member]
