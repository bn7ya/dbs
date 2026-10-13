import importlib

from dbs import upgrade
from dbs.upgrade import OK, WARN


def test_the_manager_keychain_step_finds_keyring():
    finding = upgrade.ManagerKeychain().check()

    assert finding.level == OK
    assert "system keychain" in finding.message


def test_without_keyring_the_manager_keychain_step_warns(monkeypatch):
    real_import = importlib.import_module

    def without_keyring(name, *args, **kwargs):
        if name == "keyring":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", without_keyring)

    finding = upgrade.ManagerKeychain().check()

    assert finding.level == WARN
    assert "in a file next to the data" in finding.message
    assert "django-dbs>=0.7" in finding.remedy


def test_the_manager_keychain_step_runs_with_the_others():
    assert upgrade.ManagerKeychain in upgrade.STEPS
