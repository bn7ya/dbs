import sys

from dbs import upgrade
from dbs.upgrade import OK


def test_the_manager_keychain_step_finds_keyring():
    finding = upgrade.ManagerKeychain().check()

    assert finding.level == OK
    assert "system keychain" in finding.message


def test_without_keyring_the_manager_extra_names_it_once(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", None)

    keychain = upgrade.ManagerKeychain().check()
    extra = upgrade.ManagerExtra().check()

    assert keychain.level == OK
    assert "keyring" not in keychain.message
    assert "manager extra" in keychain.message
    assert extra.level == OK
    assert "keyring" in extra.message
    assert 'pip install "django-dbs[manager]"' in extra.remedy


def test_the_manager_keychain_step_runs_with_the_others():
    assert upgrade.ManagerKeychain in upgrade.STEPS
