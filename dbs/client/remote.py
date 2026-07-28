from __future__ import annotations

import os
import posixpath
import shlex
from dataclasses import dataclass

from ..exceptions import ConfigurationError, DBSError
from ..naming import backup_filename
from ..transports.ssh import SSHSession, open_session
from .config import ServerProfile

STDERR_TAIL = 2000


@dataclass
class BackupOptions:
    database: str = "default"
    compress: bool = True
    verify: bool = True
    block_size: int | None = None
    kdf_time: int | None = None
    kdf_memory: int | None = None


@dataclass
class FetchResult:
    """Where a backup ended up locally and remotely, and how big it was."""

    local_path: str
    remote_name: str
    size: int
    pruned_local: list
    pruned_remote: list


def build_backup_command(
    profile: ServerProfile, remote_path: str, options: BackupOptions
) -> str:
    lines = []
    if profile.project_dir:
        lines.append(f"cd {shlex.quote(profile.project_dir)}")
    if profile.passphrase_transport == "env":
        lines.append("IFS= read -r DBS_PASSPHRASE")
        lines.append("export DBS_PASSPHRASE")
    if profile.django_settings_module:
        lines.append(
            "export DJANGO_SETTINGS_MODULE="
            + shlex.quote(profile.django_settings_module)
        )
    for key, value in sorted(profile.env.items()):
        lines.append(f"export {key}={shlex.quote(str(value))}")

    argv = [
        profile.python,
        profile.manage,
        "dbs_backup",
        remote_path,
        "--database",
        options.database,
    ]
    if not options.compress:
        argv.append("--no-compress")
    if not options.verify:
        argv.append("--no-verify")
    if options.block_size:
        argv += ["--block-size", str(options.block_size)]
    if options.kdf_time:
        argv += ["--kdf-time", str(options.kdf_time)]
    if options.kdf_memory:
        argv += ["--kdf-memory", str(options.kdf_memory)]
    if profile.passphrase_transport == "stdin":
        argv.append("--passphrase-stdin")

    lines.append("exec " + " ".join(shlex.quote(part) for part in argv))
    return "/bin/sh -c " + shlex.quote("\n".join(lines))


def trigger_remote_backup(
    session: SSHSession,
    profile: ServerProfile,
    passphrase: str,
    remote_name: str,
    options: BackupOptions | None = None,
) -> str:
    if "\n" in passphrase or "\r" in passphrase:
        raise ConfigurationError("A passphrase cannot contain a line break.")
    session.ensure_dir()
    remote_path = session.path_for(remote_name)
    command = build_backup_command(profile, remote_path, options or BackupOptions())
    result = session.run(
        command, stdin_line=passphrase, timeout=profile.exec_timeout
    )
    if not result.ok:
        raise DBSError(
            f"Remote dbs_backup failed on {profile.host} (exit {result.exit_status}): "
            + (result.stderr.strip()[-STDERR_TAIL:] or result.stdout.strip()[-STDERR_TAIL:])
        )
    return remote_path


def fetch_remote_backup(
    session: SSHSession, remote_name: str, local_path: str
) -> int:
    os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
    return session.pull_to(remote_name, local_path)


def server_version(session: SSHSession, profile: ServerProfile) -> str | None:
    script = f"exec {shlex.quote(profile.python)} -c 'import dbs; print(dbs.__version__)'"
    result = session.run("/bin/sh -c " + shlex.quote(script))
    return result.stdout.strip() if result.ok else None


def check_manage_command(session: SSHSession, profile: ServerProfile) -> bool:
    lines = []
    if profile.project_dir:
        lines.append(f"cd {shlex.quote(profile.project_dir)}")
    if profile.django_settings_module:
        lines.append(
            "export DJANGO_SETTINGS_MODULE="
            + shlex.quote(profile.django_settings_module)
        )
    lines.append(
        "exec "
        + " ".join(
            shlex.quote(part)
            for part in [profile.python, profile.manage, "dbs_backup", "--help"]
        )
    )
    return session.run("/bin/sh -c " + shlex.quote("\n".join(lines))).ok


def available_local_name(directory: str, prefix: str) -> str:
    for ordinal in range(1, 1000):
        name = backup_filename(prefix, ordinal=ordinal)
        if not os.path.exists(os.path.join(directory, name)):
            return name
    raise DBSError("Cannot find an unused backup filename for this second.")


def backup_and_fetch(
    profile: ServerProfile,
    passphrase: str,
    *,
    dest_dir: str | None = None,
    name: str | None = None,
    options: BackupOptions | None = None,
    fetch: bool = True,
    validate: bool = True,
    delete_remote: bool = False,
    keep: int | None = None,
    keep_remote: int | None = None,
    session: SSHSession | None = None,
) -> FetchResult:
    """Trigger a backup on the server, bring it home, and apply retention."""
    from ..retention import prune_directory, prune_remote

    directory = os.path.expanduser(dest_dir or profile.local_dir())
    os.makedirs(directory, exist_ok=True)
    remote_name = name or available_local_name(directory, profile.prefix)

    opened = session is None
    session = session or open_session(profile.ssh_target())
    if opened:
        session.__enter__()
    try:
        trigger_remote_backup(session, profile, passphrase, remote_name, options)
        local_path = os.path.join(directory, remote_name)
        size = 0
        if fetch:
            size = fetch_remote_backup(session, remote_name, local_path)
            if validate:
                _validate_locally(local_path)
            if delete_remote:
                session.delete(remote_name)
        pruned_remote = (
            prune_remote(session, keep_remote, profile.prefix)
            if keep_remote is not None and not delete_remote
            else []
        )
    finally:
        if opened:
            session.close()

    pruned_local = (
        prune_directory(directory, keep, profile.prefix) if keep is not None else []
    )
    return FetchResult(
        local_path=local_path if fetch else posixpath.join(profile.remote_dir, remote_name),
        remote_name=remote_name,
        size=size,
        pruned_local=pruned_local,
        pruned_remote=pruned_remote,
    )


def _validate_locally(path: str) -> None:
    from ..engine.validate import validate_backup

    with open(path, "rb") as fh:
        result = validate_backup(fh.read())
    if not result.ok:
        raise DBSError(f"The downloaded backup did not validate: {result.summary()}")
