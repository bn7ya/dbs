"""SSH transport config parsing (no live server needed)."""

import pytest
from django.test import override_settings

from dbs.exceptions import ConfigurationError
from dbs.transports import SSHTarget


def test_from_dict_defaults_and_security_posture():
    target = SSHTarget.from_dict({"host": "h.example.com", "username": "deploy"})
    assert target.port == 22
    assert target.remote_dir == "."
    # Fail-closed by default: unknown host keys are rejected, not auto-added.
    assert target.auto_add_host_key is False


def test_from_dict_missing_required_key():
    with pytest.raises(ConfigurationError):
        SSHTarget.from_dict({"host": "only-host"})


@override_settings(
    DBS_SSH_TARGETS={
        "offsite": {
            "host": "backups.example.com",
            "username": "deploy",
            "key_filename": "/keys/id_ed25519",
            "remote_dir": "/var/backups/app",
        }
    }
)
def test_from_settings():
    target = SSHTarget.from_settings("offsite")
    assert target.host == "backups.example.com"
    assert target.remote_dir == "/var/backups/app"
    with pytest.raises(ConfigurationError):
        SSHTarget.from_settings("missing")
