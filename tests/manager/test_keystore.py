from __future__ import annotations

import keyring
import pytest
from keyring.backends import fail

from dbs.manager import keystore, paths
from tests.manager.fake_keyring import MemoryKeyring, entry

AUTO: dict[str, str] = {}
FILE = {keystore.STORE_ENV: "file"}
KEYCHAIN = {keystore.STORE_ENV: "keychain"}


@pytest.fixture
def home(tmp_path):
    return paths.ensure_data_dir(tmp_path / "home")


@pytest.fixture
def ring(monkeypatch):
    backend = MemoryKeyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    return backend


@pytest.fixture
def no_ring(monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: fail.Keyring())


def stored(ring, home):
    return ring.entries.get(entry(keystore.SERVICE, keystore.entry_name(home)))


def test_a_keychain_with_no_priority_does_not_count(no_ring):
    assert keystore.keychain() is None


def test_a_working_keychain_is_used(ring):
    assert keystore.keychain().backend is ring


def test_without_a_keychain_the_key_stays_in_a_file_with_a_warning(home, no_ring):
    key = keystore.load(home, AUTO)

    assert key.store == keystore.FILE
    assert key.value == paths.key_path(home).read_text().strip()
    assert "no system keychain works here" in key.warning
    assert str(paths.key_path(home)) in key.warning


def test_asking_for_the_file_keeps_it_there_without_a_warning(home, ring):
    key = keystore.load(home, FILE)

    assert key.store == keystore.FILE and key.warning == ""
    assert paths.key_path(home).exists()
    assert ring.entries == {}


def test_asking_for_a_keychain_that_does_not_work_is_refused(home, no_ring):
    with pytest.raises(keystore.KeyStoreError) as refused:
        keystore.load(home, KEYCHAIN)

    assert "no system keychain works" in str(refused.value)
    assert not paths.key_path(home).exists()


def test_a_new_installation_keeps_its_key_in_the_keychain_only(home, ring):
    key = keystore.load(home, AUTO)
    again = keystore.load(home, AUTO)

    assert key.store == keystore.KEYCHAIN and key.warning == ""
    assert stored(ring, home) == key.value == again.value
    assert len(key.value) >= 50
    assert not paths.key_path(home).exists()


def test_an_existing_key_file_moves_into_the_keychain(home, ring):
    old = paths.read_key(home)

    key = keystore.load(home, AUTO)

    assert key.value == old and stored(ring, home) == old
    assert not paths.key_path(home).exists()


def test_a_key_the_keychain_does_not_give_back_stays_in_its_file(home, ring):
    old = paths.read_key(home)
    ring.forgetful = True

    key = keystore.load(home, AUTO)

    assert key.value == old and key.store == keystore.FILE
    assert paths.key_path(home).read_text().strip() == old
    with pytest.raises(keystore.KeyStoreError):
        keystore.load(home, KEYCHAIN)


def test_a_keychain_that_fails_never_mints_a_new_key(home, ring, monkeypatch):
    def refuse(service, username):
        raise RuntimeError("locked")

    monkeypatch.setattr(ring, "get_password", refuse)

    with pytest.raises(keystore.KeyStoreError) as refused:
        keystore.load(home, AUTO)

    assert "locked" in str(refused.value) and keystore.STORE_ENV in str(refused.value)
    assert not paths.key_path(home).exists()


def test_a_keychain_that_stops_answering_never_gets_its_key_replaced(home, ring, monkeypatch):
    monkeypatch.delenv(keystore.STORE_ENV, raising=False)
    keystore.load(home, AUTO)

    def broken():
        raise RuntimeError("no session bus")

    for stopped in (lambda: fail.Keyring(), broken):
        monkeypatch.setattr(keyring, "get_keyring", stopped)
        with pytest.raises(keystore.KeyStoreError) as refused:
            keystore.load(home, AUTO)

        assert "is in the system keychain" in str(refused.value)
        assert not paths.key_path(home).exists()
        assert "system keychain" in keystore.location(home)


def test_the_file_store_never_replaces_a_key_held_by_the_keychain(home, ring):
    key = keystore.load(home, AUTO)

    with pytest.raises(keystore.KeyStoreError) as refused:
        keystore.load(home, FILE)

    assert "no key file exists" in str(refused.value)
    assert not paths.key_path(home).exists()
    assert stored(ring, home) == key.value


def test_a_keychain_that_lost_the_key_is_never_given_a_new_one(home, ring):
    keystore.load(home, AUTO)
    ring.entries.clear()

    with pytest.raises(keystore.KeyStoreError) as refused:
        keystore.load(home, AUTO)

    assert "no longer holds the sealing key" in str(refused.value)
    assert ring.entries == {}
    assert not paths.key_path(home).exists()


def test_two_different_keys_stop_everything(home, ring):
    keystore.load(home, AUTO)
    paths.write_private(paths.key_path(home), "another-key")

    with pytest.raises(keystore.KeyStoreError) as refused:
        keystore.load(home, AUTO)

    assert "different sealing keys" in str(refused.value)
    assert paths.key_path(home).read_text() == "another-key"
    assert stored(ring, home) != "another-key"


def test_an_imported_key_wins_over_the_keychain(home, ring):
    keystore.load(home, AUTO)
    paths.write_private(paths.key_path(home), "imported-key")
    paths.write_private(paths.import_marker_path(home), "")

    key = keystore.load(home, AUTO)

    assert key.value == "imported-key" == stored(ring, home)
    assert not paths.key_path(home).exists()
    assert not paths.import_marker_path(home).exists()


def test_every_data_folder_has_its_own_key(tmp_path, ring):
    first = keystore.load(paths.ensure_data_dir(tmp_path / "one"), AUTO)
    second = keystore.load(paths.ensure_data_dir(tmp_path / "two"), AUTO)

    assert first.value != second.value


def test_a_key_is_carried_to_a_moved_folder_and_forgotten(home, ring, tmp_path):
    key = keystore.load(home, AUTO)
    moved = tmp_path / "moved"

    keystore.carry(home, moved, AUTO)
    keystore.forget(home, AUTO)

    assert stored(ring, moved) == key.value
    assert stored(ring, home) is None


def test_the_location_names_the_keychain_or_the_file(home, ring, monkeypatch):
    monkeypatch.delenv(keystore.STORE_ENV, raising=False)
    keystore.load(home, AUTO)

    assert keystore.location(home).startswith("system keychain (django-dbs-manager")
    assert keystore.location(home, FILE) == str(paths.key_path(home))


def test_an_unknown_store_is_refused(home):
    with pytest.raises(keystore.KeyStoreError):
        keystore.load(home, {keystore.STORE_ENV: "vault"})
