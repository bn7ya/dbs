"""Ship backups to another server over SFTP using paramiko.

Connection *profiles* live in ``settings.DBS_SSH_TARGETS`` and reference a private
key by path (or rely on an agent) rather than embedding secrets:

    DBS_SSH_TARGETS = {
        "offsite": {
            "host": "backups.example.com",
            "username": "deploy",
            "key_filename": "/home/deploy/.ssh/id_ed25519",
            "remote_dir": "/var/backups/myproject",
            "known_hosts": "/home/deploy/.ssh/known_hosts",
        }
    }

The default host-key policy is :class:`paramiko.RejectPolicy`, so an unknown
host fails closed instead of silently trusting a possible man-in-the-middle.
"""

from __future__ import annotations

import io
import posixpath
from dataclasses import dataclass

import paramiko
from django.conf import settings

from ..exceptions import ConfigurationError, DBSError


@dataclass
class SSHTarget:
    host: str
    username: str
    port: int = 22
    key_filename: str | None = None
    password: str | None = None  # discouraged; prefer key_filename / agent
    known_hosts: str | None = None
    remote_dir: str = "."
    auto_add_host_key: bool = False  # set True only for trusted/first-run setups

    @classmethod
    def from_dict(cls, data: dict) -> "SSHTarget":
        try:
            return cls(
                host=data["host"],
                username=data["username"],
                port=int(data.get("port", 22)),
                key_filename=data.get("key_filename"),
                password=data.get("password"),
                known_hosts=data.get("known_hosts"),
                remote_dir=data.get("remote_dir", "."),
                auto_add_host_key=bool(data.get("auto_add_host_key", False)),
            )
        except KeyError as exc:
            raise ConfigurationError(f"SSH target missing required key: {exc}") from exc

    @classmethod
    def from_settings(cls, name: str) -> "SSHTarget":
        targets = getattr(settings, "DBS_SSH_TARGETS", {}) or {}
        if name not in targets:
            raise ConfigurationError(f"No DBS_SSH_TARGETS entry named {name!r}.")
        return cls.from_dict(targets[name])


def _connect(target: SSHTarget) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    if target.known_hosts:
        client.load_host_keys(target.known_hosts)
    else:
        client.load_system_host_keys()
    client.set_missing_host_key_policy(
        paramiko.AutoAddPolicy() if target.auto_add_host_key else paramiko.RejectPolicy()
    )
    client.connect(
        hostname=target.host,
        port=target.port,
        username=target.username,
        password=target.password,
        key_filename=target.key_filename,
        allow_agent=True,
        look_for_keys=target.key_filename is None,
    )
    return client


def _as_bytes(data_or_path: bytes | str) -> bytes:
    if isinstance(data_or_path, (bytes, bytearray)):
        return bytes(data_or_path)
    with open(data_or_path, "rb") as fh:
        return fh.read()


def push_backup(data_or_path: bytes | str, remote_name: str, target: SSHTarget) -> str:
    """Upload backup bytes (or a local file) to ``target``; return the remote path."""
    data = _as_bytes(data_or_path)
    client = _connect(target)
    try:
        sftp = client.open_sftp()
        _ensure_remote_dir(sftp, target.remote_dir)
        remote_path = posixpath.join(target.remote_dir, remote_name)
        sftp.putfo(io.BytesIO(data), remote_path)
        return remote_path
    except OSError as exc:
        raise DBSError(f"SFTP upload failed: {exc}") from exc
    finally:
        client.close()


def pull_backup(remote_name: str, target: SSHTarget) -> bytes:
    """Download a backup from ``target`` and return its bytes."""
    client = _connect(target)
    try:
        sftp = client.open_sftp()
        remote_path = posixpath.join(target.remote_dir, remote_name)
        buffer = io.BytesIO()
        sftp.getfo(remote_path, buffer)
        return buffer.getvalue()
    except OSError as exc:
        raise DBSError(f"SFTP download failed: {exc}") from exc
    finally:
        client.close()


def list_backups(target: SSHTarget) -> list[str]:
    """List filenames present in the target's remote directory."""
    client = _connect(target)
    try:
        return sorted(client.open_sftp().listdir(target.remote_dir))
    except OSError as exc:
        raise DBSError(f"SFTP listing failed: {exc}") from exc
    finally:
        client.close()


def _ensure_remote_dir(sftp, remote_dir: str) -> None:
    parts = [p for p in remote_dir.split("/") if p]
    path = "/" if remote_dir.startswith("/") else ""
    for part in parts:
        path = posixpath.join(path, part) if path else part
        try:
            sftp.stat(path)
        except FileNotFoundError:
            sftp.mkdir(path)
