"""SSH transport: target configuration, auth wiring, and session operations."""

import os

import pytest
from django.test import override_settings

from dbs.exceptions import ConfigurationError, DBSError
from dbs.naming import backup_filename
from dbs.transports import HostKey, HostKeyError, SSHTarget, fetch_host_key, open_session
from dbs.transports.ssh import (
    check_connection,
    delete_backup,
    list_backup_details,
    list_backups,
    pull_backup,
    pull_backup_to,
    push_backup,
)
from tests.fake_ssh import AutoAddPolicy, RejectPolicy

REMOTE_DIR = "/var/backups/app"


def target(**overrides):
    values = {
        "host": "h.example.com",
        "username": "deploy",
        "remote_dir": REMOTE_DIR,
    }
    values.update(overrides)
    return SSHTarget(**values)


def test_from_dict_defaults_and_security_posture():
    parsed = SSHTarget.from_dict({"host": "h.example.com", "username": "deploy"})
    assert parsed.port == 22
    assert parsed.remote_dir == "."
    assert parsed.connect_timeout == 30.0
    # Fail-closed by default: unknown host keys are rejected, not auto-added.
    assert parsed.auto_add_host_key is False
    assert parsed.host_key_policy == "reject-unknown"


def test_from_dict_missing_required_key():
    with pytest.raises(ConfigurationError):
        SSHTarget.from_dict({"host": "only-host"})


def test_from_dict_rejects_unknown_keys():
    with pytest.raises(ConfigurationError) as excinfo:
        SSHTarget.from_dict(
            {"host": "h", "username": "u", "known_host": "/tmp/known_hosts"}
        )
    assert "known_host" in str(excinfo.value)


def test_user_and_key_file_aliases():
    parsed = SSHTarget.from_dict(
        {"host": "h", "user": "deploy", "key_file": "/keys/id_ed25519"}
    )
    assert parsed.username == "deploy"
    assert parsed.key_filename == "/keys/id_ed25519"


def test_home_relative_paths_are_expanded():
    parsed = SSHTarget.from_dict(
        {
            "host": "h",
            "username": "u",
            "key_file": "~/keys/prod.pem",
            "known_hosts": "~/.ssh/known_hosts",
        }
    )
    assert parsed.key_filename == os.path.expanduser("~/keys/prod.pem")
    assert parsed.known_hosts == os.path.expanduser("~/.ssh/known_hosts")


def test_secrets_can_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("DBS_TEST_SSH_PASSWORD", "from-env")
    monkeypatch.setenv("DBS_TEST_KEY_PASSPHRASE", "key-secret")
    parsed = SSHTarget.from_dict(
        {
            "host": "h",
            "username": "u",
            "password_env": "DBS_TEST_SSH_PASSWORD",
            "key_passphrase_env": "DBS_TEST_KEY_PASSPHRASE",
        }
    )
    assert parsed.password == "from-env"
    assert parsed.key_passphrase == "key-secret"


def test_missing_environment_secret_is_reported():
    with pytest.raises(ConfigurationError):
        SSHTarget.from_dict(
            {"host": "h", "username": "u", "password_env": "DBS_ABSENT_VARIABLE"}
        )


def test_a_target_with_no_authentication_method_is_refused():
    with pytest.raises(ConfigurationError):
        SSHTarget(host="h", username="u", use_agent=False)


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
    parsed = SSHTarget.from_settings("offsite")
    assert parsed.host == "backups.example.com"
    assert parsed.remote_dir == "/var/backups/app"
    with pytest.raises(ConfigurationError):
        SSHTarget.from_settings("missing")


def test_missing_paramiko_names_the_extra(monkeypatch):
    import dbs.transports.ssh as ssh_module

    monkeypatch.delattr("dbs.transports.ssh._paramiko")

    def explode():
        raise ImportError("no paramiko")

    monkeypatch.setattr(ssh_module, "_paramiko", explode, raising=False)
    with pytest.raises(ImportError):
        ssh_module._paramiko()


def test_connect_passes_auth_and_timeouts(fake_ssh):
    fake_ssh.make_remote_dir(REMOTE_DIR)
    with open_session(
        target(key_filename="/keys/prod.pem", key_passphrase="secret", connect_timeout=5)
    ) as session:
        session.names()

    kwargs = fake_ssh.connections[0]
    assert kwargs["key_filename"] == "/keys/prod.pem"
    assert kwargs["passphrase"] == "secret"
    assert kwargs["timeout"] == 5
    assert kwargs["auth_timeout"] == 5
    assert kwargs["look_for_keys"] is False
    assert isinstance(fake_ssh.clients[0].policy, RejectPolicy)


def test_auto_add_host_key_selects_the_permissive_policy(fake_ssh):
    fake_ssh.make_remote_dir(REMOTE_DIR)
    with open_session(target(auto_add_host_key=True)) as session:
        session.names()
    assert isinstance(fake_ssh.clients[0].policy, AutoAddPolicy)


def test_push_creates_the_directory_and_lands_atomically(fake_ssh):
    remote_path = push_backup(b"payload", backup_filename(), target())

    assert remote_path.startswith(REMOTE_DIR)
    listed = list_backups(target())
    assert len(listed) == 1
    assert not any(name.endswith(".part") for name in os.listdir(fake_ssh.remote_path(REMOTE_DIR)))
    assert os.stat(fake_ssh.remote_path(REMOTE_DIR, listed[0])).st_mode & 0o777 == 0o600
    assert pull_backup(listed[0], target()) == b"payload"


def test_listing_ignores_files_that_are_not_backups(fake_ssh):
    name = backup_filename()
    fake_ssh.write_remote(REMOTE_DIR, name, b"payload")
    fake_ssh.write_remote(REMOTE_DIR, "notes.txt", b"hello")

    assert list_backups(target()) == [name]
    assert list_backups(target(), pattern_only=False) == sorted([name, "notes.txt"])


def test_details_report_size_and_time(fake_ssh):
    name = backup_filename()
    fake_ssh.write_remote(REMOTE_DIR, name, b"1234567890")

    details = list_backup_details(target())

    assert [detail.name for detail in details] == [name]
    assert details[0].size == 10
    assert details[0].modified is not None


def test_pull_to_streams_to_disk_and_leaves_no_partial(fake_ssh, tmp_path):
    name = backup_filename()
    fake_ssh.write_remote(REMOTE_DIR, name, b"payload")
    destination = tmp_path / "local.dbs"

    assert pull_backup_to(name, str(destination), target()) == 7
    assert destination.read_bytes() == b"payload"
    assert destination.stat().st_mode & 0o777 == 0o600
    assert not (tmp_path / "local.dbs.part").exists()


def test_a_failed_pull_does_not_clobber_an_existing_file(fake_ssh, tmp_path):
    fake_ssh.make_remote_dir(REMOTE_DIR)
    destination = tmp_path / "local.dbs"
    destination.write_bytes(b"previous")

    with pytest.raises(DBSError):
        pull_backup_to(backup_filename(), str(destination), target())

    assert destination.read_bytes() == b"previous"
    assert not (tmp_path / "local.dbs.part").exists()


def test_delete_removes_the_remote_file(fake_ssh):
    name = backup_filename()
    fake_ssh.write_remote(REMOTE_DIR, name, b"payload")

    delete_backup(name, target())

    assert list_backups(target()) == []
    with pytest.raises(DBSError):
        delete_backup(name, target())


def test_run_captures_status_and_streams(fake_ssh):
    fake_ssh.on_exec(lambda command, session: (3, "out", "boom"))
    fake_ssh.make_remote_dir(REMOTE_DIR)

    with open_session(target()) as session:
        result = session.run("false", stdin_line="secret")

    assert (result.exit_status, result.stdout, result.stderr) == (3, "out", "boom")
    assert result.ok is False
    assert fake_ssh.executions[0].stdin == "secret\n"
    assert fake_ssh.executions[0].stdin_closed is True
    assert fake_ssh.commands[0]["get_pty"] is False


def test_check_connection_reports_the_facts(fake_ssh):
    fake_ssh.on_exec(lambda command, session: (0, "Linux 6.1\n", ""))
    name = backup_filename()
    fake_ssh.write_remote(REMOTE_DIR, name, b"payload")

    facts = check_connection(target())

    assert facts["system"] == "Linux 6.1"
    assert facts["host_key_policy"] == "reject-unknown"
    assert facts["remote_dir"] == REMOTE_DIR
    assert facts["backups"] == 1


def ed25519_public_line():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    return (
        ed25519.Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
        .decode()
    )


def test_host_key_parses_and_normalises_a_public_key_line():
    line = ed25519_public_line()

    key = HostKey.from_line(line + " deploy@laptop")

    assert key.key_type == "ssh-ed25519"
    assert key.line == line
    assert key.fingerprint.startswith("SHA256:")
    assert not key.fingerprint.endswith("=")


@pytest.mark.parametrize(
    "line",
    ["", "ssh-ed25519", "ssh-ed25519 not-base64!", "ssh-rsa " + "AAAAC3NzaC1lZDI1NTE5AAAAIA=="],
)
def test_host_key_refuses_a_malformed_line(line):
    with pytest.raises(ConfigurationError):
        HostKey.from_line(line)


def test_host_key_fingerprint_matches_paramiko():
    import paramiko

    key = paramiko.RSAKey.generate(1024)

    assert HostKey(key.get_name(), key.get_base64()).fingerprint == key.fingerprint


def test_a_pinned_host_key_is_normalised_and_reported():
    line = ed25519_public_line()

    pinned = target(host_key=f"  {line}  comment ")

    assert pinned.host_key == line
    assert pinned.host_key_policy == "pinned"
    assert SSHTarget.from_dict(
        {"host": "h", "username": "u", "host_key": line}
    ).host_key == line


def test_a_pinned_host_key_cannot_be_combined_with_auto_add():
    with pytest.raises(ConfigurationError, match="auto_add_host_key"):
        target(host_key=ed25519_public_line(), auto_add_host_key=True)


def test_a_pinned_host_key_is_the_only_key_trusted(fake_ssh):
    line = ed25519_public_line()
    fake_ssh.presented_key = line
    fake_ssh.make_remote_dir(REMOTE_DIR)

    with open_session(target(host_key=line, port=2222)) as session:
        session.names()

    client = fake_ssh.clients[0]
    assert client.host_keys == {"[h.example.com]:2222": {"ssh-ed25519": line}}
    assert client.system_host_keys_loaded is False
    assert client.host_keys_loaded is None
    assert isinstance(client.policy, RejectPolicy)


def test_a_changed_host_key_raises_host_key_error_and_closes(fake_ssh):
    fake_ssh.presented_key = ed25519_public_line()

    with pytest.raises(HostKeyError, match="does not match"):
        with open_session(target(host_key=ed25519_public_line(), key_filename="/k.pem")):
            pass

    assert fake_ssh.clients[0].closed is True


def test_an_unknown_host_raises_host_key_error(fake_ssh):
    fake_ssh.presented_key = ed25519_public_line()

    with pytest.raises(HostKeyError, match="not trusted"):
        with open_session(target(key_filename="/k.pem")):
            pass

    assert fake_ssh.clients[0].system_host_keys_loaded is True
    assert fake_ssh.clients[0].closed is True


def test_host_key_error_is_a_configuration_error():
    assert issubclass(HostKeyError, ConfigurationError)


def test_fetch_host_key_reads_the_presented_key_without_authenticating(
    fake_ssh, monkeypatch
):
    line = ed25519_public_line()
    fake_ssh.presented_key = line
    sockets = []
    monkeypatch.setattr(
        "dbs.transports.ssh.socket.create_connection",
        lambda address, timeout: sockets.append((address, timeout)) or "socket",
    )

    key = fetch_host_key("h.example.com", 2222, timeout=4)

    assert key.line == line
    assert sockets == [(("h.example.com", 2222), 4)]
    transport = fake_ssh.transports[0]
    assert (transport.sock, transport.start_timeout, transport.banner_timeout) == (
        "socket",
        4,
        4,
    )
    assert transport.closed is True
    assert fake_ssh.connections == []


def test_fetch_host_key_reports_an_unreachable_host(fake_ssh, monkeypatch):
    def refuse(address, timeout):
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr("dbs.transports.ssh.socket.create_connection", refuse)

    with pytest.raises(DBSError, match="Cannot reach h.example.com:22"):
        fetch_host_key("h.example.com")


def test_fetch_host_key_reports_a_failed_handshake_and_closes(fake_ssh, monkeypatch):
    from tests.fake_ssh import SSHException

    fake_ssh.handshake_error = SSHException("Error reading SSH protocol banner")
    monkeypatch.setattr(
        "dbs.transports.ssh.socket.create_connection", lambda address, timeout: "socket"
    )

    with pytest.raises(DBSError, match="handshake"):
        fetch_host_key("h.example.com")

    assert fake_ssh.transports[0].closed is True


def openssh_private_key(algorithm, passphrase=None):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

    private = {
        "ed25519": lambda: ed25519.Ed25519PrivateKey.generate(),
        "ecdsa": lambda: ec.generate_private_key(ec.SECP256R1()),
        "rsa": lambda: rsa.generate_private_key(public_exponent=65537, key_size=2048),
    }[algorithm]()
    encryption = (
        serialization.BestAvailableEncryption(passphrase.encode())
        if passphrase
        else serialization.NoEncryption()
    )
    return private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, encryption
    ).decode()


@pytest.mark.parametrize(
    ("algorithm", "key_name"),
    [("ed25519", "ssh-ed25519"), ("ecdsa", "ecdsa-sha2-nistp256"), ("rsa", "ssh-rsa")],
)
def test_a_stored_private_key_loads_from_memory(algorithm, key_name):
    import paramiko

    from dbs.transports.ssh import _load_private_key

    key = _load_private_key(
        paramiko, target(private_key=openssh_private_key(algorithm), use_agent=False)
    )

    assert key.get_name() == key_name


def test_a_stored_private_key_loads_with_its_passphrase():
    import paramiko

    from dbs.transports.ssh import _load_private_key

    stored = target(
        private_key=openssh_private_key("rsa", passphrase="hunter2"),
        key_passphrase="hunter2",
        use_agent=False,
    )

    assert _load_private_key(paramiko, stored).get_name() == "ssh-rsa"


def test_an_encrypted_stored_key_without_its_passphrase_is_named():
    import paramiko

    from dbs.transports.ssh import _load_private_key

    stored = target(private_key=openssh_private_key("ed25519", passphrase="x"), use_agent=False)

    with pytest.raises(ConfigurationError, match="encrypted"):
        _load_private_key(paramiko, stored)


def test_an_unreadable_stored_key_is_refused():
    import paramiko

    from dbs.transports.ssh import _load_private_key

    stored = target(private_key="-----BEGIN NOTHING-----\nAAAA\n-----END NOTHING-----\n")

    with pytest.raises(ConfigurationError, match="could not be read"):
        _load_private_key(paramiko, stored)


def test_a_password_target_without_the_agent_offers_no_local_keys(fake_ssh):
    fake_ssh.make_remote_dir(REMOTE_DIR)
    with open_session(target(password="s3cret", use_agent=False)) as session:
        session.names()

    assert fake_ssh.connections[0]["look_for_keys"] is False


def test_an_agent_target_without_a_key_still_looks_for_local_keys(fake_ssh):
    fake_ssh.make_remote_dir(REMOTE_DIR)
    with open_session(target()) as session:
        session.names()

    assert fake_ssh.connections[0]["look_for_keys"] is True
