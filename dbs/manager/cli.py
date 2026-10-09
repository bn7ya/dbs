from __future__ import annotations

import argparse
import getpass
import json
import os
import signal
import socket
import sys
import webbrowser

from . import paths
from .conf import (
    DATABASE_URL_ENV,
    DEFAULT_HOST,
    DEFAULT_PORT,
    HOME_ENV,
    HOST_ENV,
    INSTANCE_LEASE,
    LEASE_SECONDS,
    SETTINGS_MODULE,
    is_loopback,
)

PROG = "django_dbs"
WILDCARD_HOSTS = ("0.0.0.0", "::", "")
SERVER_THREADS = 8


class CommandFailed(Exception):
    pass


class VersionAction(argparse.Action):
    def __init__(
        self,
        option_strings,
        dest=argparse.SUPPRESS,
        default=argparse.SUPPRESS,
        **kwargs,
    ):
        super().__init__(option_strings, dest=dest, default=default, nargs=0, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        from dbs import __version__

        print(f"{PROG} {__version__}")
        parser.exit()


def data_dir_option(parser):
    parser.add_argument(
        "--data-dir",
        help=f"Where the manager keeps its data. Defaults to ${HOME_ENV}, then the "
        "platform's application data folder.",
    )


def database_option(parser):
    parser.add_argument(
        "--database-url",
        help=f"A sqlite://, postgres:// or mysql:// URL. Defaults to ${DATABASE_URL_ENV}, "
        "then a SQLite file in the data directory.",
    )


def build_parser():
    parser = argparse.ArgumentParser(
        prog=PROG, description="Run and maintain the standalone DBS manager."
    )
    parser.add_argument(
        "--version", action=VersionAction, help="Print the version and exit."
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    run = commands.add_parser("run", help="Start the manager and open it in a browser.")
    run.add_argument("--host", default=DEFAULT_HOST, help="Address to listen on.")
    run.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"Port to listen on. Defaults to {DEFAULT_PORT}, or a free one if it is taken.",
    )
    run.add_argument("--no-browser", action="store_true", help="Do not open a browser.")
    data_dir_option(run)
    database_option(run)
    run.set_defaults(handler=command_run)

    where = commands.add_parser("paths", help="Show where the manager keeps its files.")
    data_dir_option(where)
    where.set_defaults(handler=command_paths)

    create = commands.add_parser("createuser", help="Add an account that can sign in.")
    create.add_argument("name")
    create.add_argument(
        "--password-stdin", action="store_true", help="Read the password from stdin."
    )
    data_dir_option(create)
    database_option(create)
    create.set_defaults(handler=command_createuser)

    password = commands.add_parser("password", help="Change an account's password.")
    password.add_argument("name")
    password.add_argument(
        "--password-stdin", action="store_true", help="Read the password from stdin."
    )
    data_dir_option(password)
    database_option(password)
    password.set_defaults(handler=command_password)

    export = commands.add_parser(
        "export", help="Write the manager's data to one backup file."
    )
    export.add_argument(
        "file", nargs="?", help="Where to write it. Defaults to a dated name here."
    )
    export.add_argument(
        "--with-backups",
        action="store_true",
        help="Include the backups the manager holds.",
    )
    export.add_argument(
        "--passphrase-stdin",
        action="store_true",
        help="Read the passphrase from stdin.",
    )
    data_dir_option(export)
    database_option(export)
    export.set_defaults(handler=command_export)

    restore = commands.add_parser(
        "import", help="Load an export into a data directory."
    )
    restore.add_argument("file")
    restore.add_argument(
        "--replace",
        action="store_true",
        help="Replace the servers this directory holds.",
    )
    restore.add_argument(
        "--passphrase-stdin",
        action="store_true",
        help="Read the passphrase from stdin.",
    )
    data_dir_option(restore)
    database_option(restore)
    restore.set_defaults(handler=command_import)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "handler", None) is None:
        parser.print_help()
        return 2
    try:
        return args.handler(args) or 0
    except CommandFailed as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return 1


def resolve(args):
    return paths.ensure_data_dir(
        paths.resolve_data_dir(getattr(args, "data_dir", None))
    )


def configure(data_dir, database_url=None, host=None):
    paths.ensure_key(data_dir)
    os.environ[HOME_ENV] = str(data_dir)
    os.environ["DJANGO_SETTINGS_MODULE"] = SETTINGS_MODULE
    if database_url:
        os.environ[DATABASE_URL_ENV] = database_url
    if host and host not in WILDCARD_HOSTS and not is_loopback(host):
        os.environ.setdefault(HOST_ENV, host)


def setup_django(data_dir, database_url=None, host=None):
    configure(data_dir, database_url, host)
    import django
    from django.core.management import call_command

    django.setup()
    call_command("migrate", interactive=False, verbosity=0)


def command_paths(args):
    data_dir = resolve(args)
    database = os.environ.get(DATABASE_URL_ENV) or str(paths.database_path(data_dir))
    rows = (
        ("data directory", data_dir),
        ("database", database),
        ("secret key", paths.key_path(data_dir)),
        ("backups", paths.backups_path(data_dir)),
        ("log", paths.log_path(data_dir)),
    )
    for label, value in rows:
        print(f"{label:<15} {value}")
    return 0


def read_password(from_stdin):
    if from_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("Password: ")
        if getpass.getpass("Password again: ") != password:
            raise CommandFailed("the two passwords differ.")
    if not password:
        raise CommandFailed("the password is empty.")
    return password


def checked_password(password, username):
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    from .accounts.repositories import UserRepository

    try:
        validate_password(password, user=UserRepository().unsaved(username))
    except ValidationError as exc:
        raise CommandFailed(" ".join(exc.messages)) from exc
    return password


def command_createuser(args):
    setup_django(resolve(args), args.database_url)
    from dbs import audit

    from .accounts.repositories import UserRepository

    users = UserRepository()
    if users.find_by_username(args.name) is not None:
        raise CommandFailed(f"an account named {args.name!r} already exists.")
    password = checked_password(read_password(args.password_stdin), args.name)
    users.create_superuser(username=args.name, password=password)
    audit.record("account.create", target=args.name)
    print(f"Added {args.name}. Sign in at the address django_dbs run prints.")
    return 0


def command_password(args):
    setup_django(resolve(args), args.database_url)
    from dbs import audit

    from .accounts.repositories import UserRepository

    users = UserRepository()
    user = users.find_by_username(args.name)
    if user is None:
        raise CommandFailed(f"there is no account named {args.name!r}.")
    password = checked_password(read_password(args.password_stdin), args.name)
    users.set_password(user, password)
    audit.record("account.password", target=user.get_username())
    print(f"Changed the password of {user.get_username()}.")
    return 0


def read_passphrase(from_stdin, confirm):
    if from_stdin:
        passphrase = sys.stdin.readline().rstrip("\n")
    else:
        passphrase = getpass.getpass("Export passphrase: ")
        if confirm and getpass.getpass("Export passphrase again: ") != passphrase:
            raise CommandFailed("the two passphrases differ.")
    if not passphrase:
        raise CommandFailed("the passphrase is empty.")
    return passphrase


def command_export(args):
    setup_django(resolve(args), args.database_url)
    from .transfer import TransferError, default_export_name, export_manager

    output = os.path.abspath(args.file or default_export_name())
    passphrase = read_passphrase(args.passphrase_stdin, confirm=True)
    try:
        container = export_manager(output, passphrase, with_backups=args.with_backups)
    except TransferError as exc:
        raise CommandFailed(str(exc)) from exc
    print(f"Wrote {output} ({len(container)} bytes). Keep the passphrase with it.")
    return 0


def command_import(args):
    data_dir = resolve(args)
    setup_django(data_dir, args.database_url)
    from dbs import leases

    from .transfer import TransferError, import_manager

    owner = leases.process_owner()
    if not take_instance_lease(owner):
        raise CommandFailed(
            "django_dbs run is using this data directory; stop it first."
        )
    try:
        passphrase = read_passphrase(args.passphrase_stdin, confirm=False)
        result = import_manager(args.file, passphrase, replace=args.replace)
    except TransferError as exc:
        raise CommandFailed(str(exc)) from exc
    finally:
        leases.release(INSTANCE_LEASE, owner)
    print(f"Imported {result.records_loaded} records into {data_dir}.")
    return 0


def pid_running(pid):
    if os.name != "posix":
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def abandoned(owner):
    host, _, pid = owner.rpartition(":")
    if host != socket.gethostname() or not pid.isdigit():
        return False
    return int(pid) != os.getpid() and not pid_running(int(pid))


def take_instance_lease(owner):
    from dbs import leases

    if leases.acquire(INSTANCE_LEASE, owner, LEASE_SECONDS):
        return True
    holder = leases.holder(INSTANCE_LEASE)
    if holder is not None and abandoned(holder.owner):
        leases.release(INSTANCE_LEASE, holder.owner)
        return leases.acquire(INSTANCE_LEASE, owner, LEASE_SECONDS)
    return False


def read_instance(data_dir):
    try:
        return json.loads(paths.instance_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def browser_host(host):
    if host in WILDCARD_HOSTS:
        return "127.0.0.1"
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


def open_running(data_dir, no_browser):
    instance = read_instance(data_dir)
    url = instance.get("url")
    if not url:
        print("Another django_dbs run already uses this data directory.")
        return 0
    print(f"The DBS manager is already running at {url}")
    if not no_browser:
        webbrowser.open(url)
    return 0


def create_server(host, port):
    from django.core.wsgi import get_wsgi_application
    from waitress.server import create_server as waitress_server

    application = get_wsgi_application()
    options = {"threads": SERVER_THREADS, "ident": PROG}
    if port is not None:
        return waitress_server(application, host=host, port=port, **options)
    try:
        return waitress_server(application, host=host, port=DEFAULT_PORT, **options)
    except OSError:
        return waitress_server(application, host=host, port=0, **options)


def first_page(base):
    from .accounts.services import SetupService
    from .accounts.services.setup_service import write_token

    if SetupService().needed():
        return f"{base}/setup?token={write_token()}"
    return f"{base}/"


def stop_on_signal(signum, frame):
    raise KeyboardInterrupt


def warn_if_exposed(host):
    if is_loopback(host):
        return
    print(
        f"Warning: listening on {host}, so anyone who can reach this address can open "
        f"the sign-in page. Set ${HOST_ENV} to the name you browse to, and prefer an SSH "
        "tunnel to 127.0.0.1.",
        file=sys.stderr,
    )


def command_run(args):
    data_dir = resolve(args)
    setup_django(data_dir, args.database_url, args.host)
    from dbs import audit, leases

    from .runner import get_runner
    from .scheduler import Scheduler

    owner = leases.process_owner()
    if not take_instance_lease(owner):
        return open_running(data_dir, args.no_browser)

    runner = get_runner()
    scheduler = Scheduler()
    server = None
    try:
        audit.interrupt()
        runner.start()
        scheduler.start()
        server = create_server(args.host, args.port)
        base = f"http://{browser_host(args.host)}:{server.effective_port}"
        paths.write_private(
            paths.instance_path(data_dir),
            json.dumps(
                {
                    "host": args.host,
                    "port": server.effective_port,
                    "pid": os.getpid(),
                    "url": f"{base}/",
                }
            ),
        )
        url = first_page(base)
        warn_if_exposed(args.host)
        print(f"The DBS manager is running at {url}", flush=True)
        print("Press Ctrl+C to stop it.", flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        signal.signal(signal.SIGINT, stop_on_signal)
        signal.signal(signal.SIGTERM, stop_on_signal)
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        if server is not None:
            server.close()
        scheduler.stop()
        runner.shutdown(wait=False)
        leases.release(INSTANCE_LEASE, owner)
        try:
            paths.instance_path(data_dir).unlink()
        except FileNotFoundError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
