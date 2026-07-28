from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading

from ..exceptions import DBSError
from ..naming import sorted_backups
from ..retention import prune_directory, prune_remote
from ..scheduling import install_stop_handlers, parse_interval, run_schedule
from ..transports.ssh import open_session
from .config import load_client_config, resolve_client_passphrase
from .remote import (
    BackupOptions,
    backup_and_fetch,
    check_manage_command,
    fetch_remote_backup,
    server_version,
)
from .sample import SAMPLE_CONFIG

logger = logging.getLogger("dbs")

SERVER_COMMANDS = ("test-connection", "list", "backup", "pull", "push", "prune", "schedule")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dbs-client",
        description="Take encrypted DBS backups from a server over SSH.",
    )
    parser.add_argument("--config", help="Path to the client config file.")
    parser.add_argument("--server", default=None, help="Which server profile to use.")
    parser.add_argument("--connect-timeout", type=float, default=None, help="SSH connect timeout in seconds.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Log what is happening.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def with_server(name, help_text):
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument("--server", default=argparse.SUPPRESS, help="Which server profile to use.")
        sub.add_argument("--connect-timeout", type=float, default=argparse.SUPPRESS, help="SSH connect timeout in seconds.")
        return sub

    def with_backup_flags(sub):
        sub.add_argument("--database", default=None, help="Database alias to back up.")
        sub.add_argument("--no-compress", action="store_true", help="Disable zlib compression.")
        sub.add_argument("--no-verify", action="store_true", help="Skip the server's verify-after-write check.")
        sub.add_argument("--block-size", type=int, default=None, help="Block size in bytes.")
        sub.add_argument("--kdf-time", type=int, default=None, help="Argon2 time cost.")
        sub.add_argument("--kdf-memory", type=int, default=None, help="Argon2 memory cost (KiB).")
        sub.add_argument("--exec-timeout", type=float, default=None, help="Seconds to allow the remote backup to run.")
        return sub

    with_server("test-connection", "Check the SSH connection and the server's DBS install.")

    listing = with_server("list", "List the backups on the server.")
    listing.add_argument("--prefix", default=None, help="Only show this filename prefix.")
    listing.add_argument("--all", action="store_true", help="Include files that are not DBS backups.")
    listing.add_argument("--json", action="store_true", help="Print machine-readable output.")

    backup = with_backup_flags(with_server("backup", "Back up on the server and download the file."))
    backup.add_argument("--dest", default=None, help="Local directory to download into.")
    backup.add_argument("--prefix", default=None, help="Filename prefix for this project.")
    backup.add_argument("--name", default=None, help="Use an exact backup filename.")
    backup.add_argument("--keep", type=int, default=None, help="How many local backups to retain.")
    backup.add_argument("--keep-remote", type=int, default=None, help="How many remote backups to retain.")
    backup.add_argument("--no-fetch", action="store_true", help="Leave the backup on the server.")
    backup.add_argument("--delete-remote", action="store_true", help="Remove the remote copy once downloaded.")
    backup.add_argument("--no-validate", action="store_true", help="Skip validating the downloaded file.")

    pull = with_server("pull", "Download a backup that already exists on the server.")
    pull.add_argument("name", nargs="?", help="Backup filename; omit with --latest.")
    pull.add_argument("--latest", action="store_true", help="Download the newest backup.")
    pull.add_argument("--dest", default=None, help="Local directory to download into.")
    pull.add_argument("--prefix", default=None, help="Only consider this filename prefix.")
    pull.add_argument("--no-validate", action="store_true", help="Skip validating the downloaded file.")

    push = with_server("push", "Upload a local backup file to the server.")
    push.add_argument("path", help="Local .dbs file to upload.")
    push.add_argument("--remote-name", default=None, help="Name to store it under remotely.")

    prune = with_server("prune", "Apply retention locally, remotely, or both.")
    prune.add_argument("--prefix", default=None, help="Only consider this filename prefix.")
    prune.add_argument("--keep", type=int, default=None, help="How many local backups to retain.")
    prune.add_argument("--keep-remote", type=int, default=None, help="How many remote backups to retain.")
    prune.add_argument("--dest", default=None, help="Local directory to prune.")
    prune.add_argument("--local-only", action="store_true", help="Do not touch the server.")
    prune.add_argument("--remote-only", action="store_true", help="Do not touch local files.")
    prune.add_argument("--dry-run", action="store_true", help="Report what would be removed.")

    schedule = with_backup_flags(with_server("schedule", "Back up and download on a repeating interval."))
    schedule.add_argument("--interval", default=None, help="How often to back up: 90s, 30m, 6h, 1d.")
    schedule.add_argument("--dest", default=None, help="Local directory to download into.")
    schedule.add_argument("--prefix", default=None, help="Filename prefix for this project.")
    schedule.add_argument("--keep", type=int, default=None, help="How many local backups to retain.")
    schedule.add_argument("--keep-remote", type=int, default=None, help="How many remote backups to retain.")
    schedule.add_argument("--delete-remote", action="store_true", help="Remove each remote copy once downloaded.")
    schedule.add_argument("--no-validate", action="store_true", help="Skip validating downloaded files.")
    schedule.add_argument("--once", action="store_true", help="Run a single cycle and exit.")

    validate = subparsers.add_parser("validate", help="Check a local backup file.")
    validate.add_argument("path", help="Local .dbs file.")
    validate.add_argument("--structure-only", action="store_true", help="Skip the decryption check.")

    init = subparsers.add_parser("init", help="Write a starter client config.")
    init.add_argument("--path", default="dbs-client.toml", help="Where to write it.")
    init.add_argument("--print", dest="to_stdout", action="store_true", help="Print it instead of writing a file.")

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.verbose:
        logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(message)s")

    try:
        return _dispatch(args)
    except DBSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 1


def _dispatch(args) -> int:
    handlers = {
        "init": _init,
        "validate": _validate,
        "test-connection": _test_connection,
        "list": _list,
        "backup": _backup,
        "pull": _pull,
        "push": _push,
        "prune": _prune,
        "schedule": _schedule,
    }
    return handlers[args.command](args)


def _profile(args):
    config = load_client_config(args.config)
    profile = config.server(getattr(args, "server", None))
    if getattr(args, "connect_timeout", None):
        profile.connect_timeout = args.connect_timeout
    for attribute in ("prefix", "database", "exec_timeout"):
        value = getattr(args, attribute, None)
        if value is not None:
            setattr(profile, attribute, value)
    return profile


def _options(args, profile) -> BackupOptions:
    return BackupOptions(
        database=profile.database,
        compress=not getattr(args, "no_compress", False),
        verify=not getattr(args, "no_verify", False),
        block_size=getattr(args, "block_size", None),
        kdf_time=getattr(args, "kdf_time", None),
        kdf_memory=getattr(args, "kdf_memory", None),
    )


def _retention(args, profile):
    keep = args.keep if args.keep is not None else profile.keep
    keep_remote = (
        args.keep_remote if args.keep_remote is not None else profile.keep_remote
    )
    return keep, keep_remote


def _init(args) -> int:
    if args.to_stdout:
        sys.stdout.write(SAMPLE_CONFIG)
        return 0
    path = os.path.expanduser(args.path)
    try:
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        print(f"error: {path} already exists; nothing was changed.", file=sys.stderr)
        return 1
    with os.fdopen(handle, "w") as fh:
        fh.write(SAMPLE_CONFIG)
    print(f"Wrote {path} (mode 600). Edit it, then run: dbs-client test-connection")
    return 0


def _validate(args) -> int:
    from ..engine.validate import validate_backup

    with open(args.path, "rb") as fh:
        data = fh.read()
    passphrase = None
    if not args.structure_only:
        passphrase = os.environ.get("DBS_PASSPHRASE")
        if not passphrase and sys.stdin.isatty():
            import getpass

            passphrase = getpass.getpass("DBS passphrase: ")
    result = validate_backup(data, passphrase)
    print(result.summary())
    return 0 if result.ok else 1


def _test_connection(args) -> int:
    profile = _profile(args)
    checks = []
    with open_session(profile.ssh_target()) as session:
        checks.append(("ssh authentication", True, f"{profile.username}@{profile.host}:{profile.port}"))
        checks.append(
            ("host key policy", not profile.auto_add_host_key, profile.ssh_target().host_key_policy)
        )
        uname = session.run("uname -sr")
        checks.append(("remote shell", uname.ok, uname.stdout.strip() or uname.stderr.strip()))
        try:
            session.ensure_dir()
            checks.append(("remote directory", True, profile.remote_dir))
        except DBSError as exc:
            checks.append(("remote directory", False, str(exc)))
        version = server_version(session, profile)
        checks.append(("django-dbs on server", version is not None, version or "not importable"))
        manage_ok = check_manage_command(session, profile)
        checks.append(
            ("manage.py dbs_backup", manage_ok, "ready" if manage_ok else "not runnable")
        )
        try:
            checks.append(("backups present", True, str(len(session.names()))))
        except DBSError as exc:
            checks.append(("backups present", False, str(exc)))

    width = max(len(label) for label, _, _ in checks)
    for label, ok, detail in checks:
        print(f"[{'ok' if ok else 'FAIL'}] {label.ljust(width)}  {detail}")
    return 0 if all(ok for _, ok, _ in checks) else 1


def _list(args) -> int:
    profile = _profile(args)
    with open_session(profile.ssh_target()) as session:
        if args.all:
            entries = [(name, None, None) for name in session.names(pattern_only=False)]
        else:
            entries = [
                (item.name, item.size, item.modified)
                for item in session.details()
                if args.prefix is None or item.name.startswith(f"{args.prefix}-")
            ]

    if args.json:
        print(json.dumps(
            [
                {
                    "name": name,
                    "size": size,
                    "modified": modified.isoformat() if modified else None,
                }
                for name, size, modified in entries
            ],
            indent=2,
        ))
        return 0

    if not entries:
        print(f"No backups in {profile.remote_dir} on {profile.host}.")
        return 0
    for name, size, modified in entries:
        stamp = modified.strftime("%Y-%m-%d %H:%M:%SZ") if modified else ""
        measure = f"{size:>12,}" if size is not None else " " * 12
        print(f"{name}  {measure}  {stamp}")
    return 0


def _backup(args) -> int:
    profile = _profile(args)
    passphrase = resolve_client_passphrase(profile)
    keep, keep_remote = _retention(args, profile)
    result = backup_and_fetch(
        profile,
        passphrase,
        dest_dir=args.dest,
        name=args.name,
        options=_options(args, profile),
        fetch=not args.no_fetch,
        validate=not args.no_validate,
        delete_remote=args.delete_remote,
        keep=keep,
        keep_remote=keep_remote,
    )
    _report(result, fetched=not args.no_fetch)
    return 0


def _pull(args) -> int:
    profile = _profile(args)
    if not args.name and not args.latest:
        print("error: give a backup name or --latest.", file=sys.stderr)
        return 1

    directory = os.path.expanduser(args.dest or profile.local_dir())
    os.makedirs(directory, exist_ok=True)
    with open_session(profile.ssh_target()) as session:
        name = args.name
        if not name:
            candidates = sorted_backups(session.names(), args.prefix)
            if not candidates:
                print(f"error: no backups in {profile.remote_dir}.", file=sys.stderr)
                return 1
            name = candidates[-1]
        local_path = os.path.join(directory, name)
        size = fetch_remote_backup(session, name, local_path)

    if not args.no_validate:
        from .remote import _validate_locally

        _validate_locally(local_path)
    print(f"Downloaded {name} ({size:,} bytes) to {local_path}")
    return 0


def _push(args) -> int:
    profile = _profile(args)
    name = args.remote_name or os.path.basename(args.path)
    with open_session(profile.ssh_target()) as session:
        remote_path = session.push(args.path, name)
    print(f"Uploaded {args.path} to {profile.host}:{remote_path}")
    return 0


def _prune(args) -> int:
    profile = _profile(args)
    keep, keep_remote = _retention(args, profile)
    prefix = args.prefix or profile.prefix
    verb = "Would remove" if args.dry_run else "Removed"

    if not args.remote_only:
        if keep is None:
            print("error: --keep is required to prune locally.", file=sys.stderr)
            return 1
        directory = os.path.expanduser(args.dest or profile.local_dir())
        removed = prune_directory(directory, keep, prefix, dry_run=args.dry_run)
        print(f"{verb} {len(removed)} local backup(s) in {directory}.")
        for name in removed:
            print(f"  {name}")

    if not args.local_only:
        if keep_remote is None:
            print("error: --keep-remote is required to prune the server.", file=sys.stderr)
            return 1
        with open_session(profile.ssh_target()) as session:
            removed = prune_remote(session, keep_remote, prefix, dry_run=args.dry_run)
        print(f"{verb} {len(removed)} remote backup(s) on {profile.host}.")
        for name in removed:
            print(f"  {name}")
    return 0


def _schedule(args) -> int:
    profile = _profile(args)
    passphrase = resolve_client_passphrase(profile, allow_prompt=False)
    keep, keep_remote = _retention(args, profile)
    interval = parse_interval(args.interval or profile.interval or "24h")
    options = _options(args, profile)

    def cycle():
        result = backup_and_fetch(
            profile,
            passphrase,
            dest_dir=args.dest,
            options=options,
            validate=not args.no_validate,
            delete_remote=args.delete_remote,
            keep=keep,
            keep_remote=keep_remote,
        )
        _report(result, fetched=True)

    stop = threading.Event()
    if not args.once:
        install_stop_handlers(stop)
        print(
            f"Backing up {profile.name} every {args.interval or profile.interval or '24h'}; "
            "press Ctrl-C to stop."
        )
    failures = run_schedule(cycle, interval, once=args.once, stop=stop)
    return 1 if failures else 0


def _report(result, *, fetched: bool) -> None:
    if fetched:
        print(f"Downloaded {result.remote_name} ({result.size:,} bytes) to {result.local_path}")
    else:
        print(f"Created {result.remote_name} on the server at {result.local_path}")
    for name in result.pruned_local:
        print(f"  removed local {name}")
    for name in result.pruned_remote:
        print(f"  removed remote {name}")
