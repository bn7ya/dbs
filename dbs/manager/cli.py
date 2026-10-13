from __future__ import annotations

import argparse
import getpass
import ipaddress
import json
import os
import signal
import sys
import webbrowser

from . import keystore, paths
from .processes import abandoned
from .terminal import CommandFailed, parsers
from .conf import (
    DATABASE_URL_ENV,
    DEFAULT_HOST,
    DEFAULT_PORT,
    HOME_ENV,
    HOST_ENV,
    INSTANCE_LEASE,
    LEASE_SECONDS,
    SETTINGS_MODULE,
    TRUSTED_PROXY_ENV,
    is_loopback,
)

PROG = "django_dbs"
WILDCARD_HOSTS = ("0.0.0.0", "::", "")
SERVER_THREADS = 8
ROLES = ("master", "admin", "operator", "viewer")
ASSIGNABLE_ROLES = ("admin", "operator", "viewer")


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


def password_stdin_option(parser):
    parser.add_argument(
        "--password-stdin", action="store_true", help="Read the password from stdin."
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
    run.add_argument(
        "--trusted-proxy",
        action="append",
        metavar="CIDR",
        help="The address range of the TLS reverse proxy in front of the manager. Its "
        "X-Forwarded-Proto and X-Forwarded-For are believed; no one else's are. "
        "Repeat for more.",
    )
    run.add_argument(
        "--allow-insecure-http",
        action="store_true",
        help="Listen beyond this computer over plain HTTP. Passwords and sessions then "
        "cross the network unencrypted.",
    )
    data_dir_option(run)
    database_option(run)
    run.set_defaults(handler=command_run)

    where = commands.add_parser("paths", help="Show where the manager keeps its files.")
    data_dir_option(where)
    where.set_defaults(handler=command_paths)

    create = commands.add_parser("createuser", help="Add an account that can sign in.")
    create.add_argument("name")
    create.add_argument(
        "--role",
        choices=ROLES,
        help="What the account may do. The first account is always the master; "
        "every later one needs admin, operator or viewer.",
    )
    password_stdin_option(create)
    data_dir_option(create)
    database_option(create)
    create.set_defaults(handler=command_createuser)

    password = commands.add_parser(
        "password", help="Set an account's password; its 30 days start again."
    )
    password.add_argument("name")
    password_stdin_option(password)
    data_dir_option(password)
    database_option(password)
    password.set_defaults(handler=command_password)

    account = commands.add_parser(
        "account",
        help="List accounts, set their roles, switch them off or on, reset their "
        "two-factor sign-in.",
    )
    verbs = account.add_subparsers(dest="verb", metavar="VERB", required=True)
    listed = verbs.add_parser("list", help="List the accounts.")
    listed.set_defaults(handler=command_account_list)
    role = verbs.add_parser(
        "role",
        help="Set an account's role. Giving it master hands the master role over.",
    )
    role.add_argument("name")
    role.add_argument("role", choices=ROLES)
    role.set_defaults(handler=command_account_role)
    disable = verbs.add_parser("disable", help="Stop an account from signing in.")
    disable.add_argument("name")
    disable.set_defaults(handler=command_account_disable)
    enable = verbs.add_parser("enable", help="Let a disabled account sign in again.")
    enable.add_argument("name")
    enable.set_defaults(handler=command_account_enable)
    reset = verbs.add_parser(
        "reset-2fa",
        help="Forget an account's authenticator and recovery codes; it sets them up "
        "again at its next sign-in.",
    )
    reset.add_argument("name")
    reset.set_defaults(handler=command_account_reset)
    for verb in (listed, role, disable, enable, reset):
        data_dir_option(verb)
        database_option(verb)

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
        help="Replace an installation that already manages servers. It is moved "
        "aside, never deleted.",
    )
    restore.add_argument(
        "--yes",
        action="store_true",
        help="Do not ask before replacing an installation sealed with another key.",
    )
    restore.add_argument(
        "--passphrase-stdin",
        action="store_true",
        help="Read the passphrase from stdin.",
    )
    data_dir_option(restore)
    database_option(restore)
    restore.set_defaults(handler=command_import)

    parsers.register(commands, location)
    return parser


def location(parser):
    data_dir_option(parser)
    database_option(parser)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "handler", None) is None:
        parser.print_help()
        return 2
    try:
        if isinstance(args.handler, str):
            return command_terminal(args)
        return args.handler(args) or 0
    except CommandFailed as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return 1
    except keystore.KeyStoreError as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(f"{PROG}: stopped.", file=sys.stderr)
        return 130


def command_terminal(args):
    setup_django(resolve(args), args.database_url)
    from .terminal.dispatch import dispatch

    return dispatch(args)


def resolve(args):
    wanted = paths.resolve_data_dir(getattr(args, "data_dir", None))
    finished = paths.finish_interrupted_import(wanted)
    if finished is not None:
        print(
            f"Finished an import that stopped half way: {finished} is now {wanted}.",
            file=sys.stderr,
        )
    return paths.ensure_data_dir(wanted)


def configure(data_dir, database_url=None, host=None, proxies=None):
    os.environ[HOME_ENV] = str(data_dir)
    os.environ["DJANGO_SETTINGS_MODULE"] = SETTINGS_MODULE
    if database_url:
        os.environ[DATABASE_URL_ENV] = database_url
    if host and host not in WILDCARD_HOSTS and not is_loopback(host):
        os.environ.setdefault(HOST_ENV, host)
    if proxies:
        os.environ[TRUSTED_PROXY_ENV] = ",".join(proxies)


def setup_django(data_dir, database_url=None, host=None, proxies=None):
    configure(data_dir, database_url, host, proxies)
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
        ("secret key", keystore.location(data_dir)),
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


def checked_password(password, user):
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    try:
        validate_password(password, user=user)
    except ValidationError as exc:
        raise CommandFailed(" ".join(exc.messages)) from exc
    return password


def refused(exc):
    from .adapters.problems import problem

    return CommandFailed(problem(exc))


def command_createuser(args):
    setup_django(resolve(args), args.database_url)
    from rest_framework.exceptions import APIException

    from .accounts.repositories import UserRepository
    from .accounts.services import AccountManagementService

    first = not UserRepository().any_exist()
    if not first and args.role is None:
        raise CommandFailed(
            "choose what the account may do with --role admin, operator or viewer."
        )
    if not first and args.role == "master":
        raise CommandFailed(
            "there is a master account already; hand it over with: "
            f"{PROG} account role {args.name} master"
        )
    password = read_password(args.password_stdin)
    try:
        account = AccountManagementService(None).create(
            username=args.name, password=password, role=args.role or "master"
        )
    except APIException as exc:
        raise refused(exc) from exc
    if account.is_master:
        print(f"Added {args.name}, the master account.")
    else:
        print(
            f"Added {args.name} as {account.role}. It sets up two-factor sign-in and "
            "chooses its own password the first time it signs in."
        )
    print(f"Sign in at the address {PROG} run prints.")
    return 0


def command_password(args):
    setup_django(resolve(args), args.database_url)
    from dbs import audit

    from .accounts.repositories import UserRepository

    users = UserRepository()
    user = users.find_by_username(args.name)
    if user is None:
        raise CommandFailed(f"there is no account named {args.name!r}.")
    password = checked_password(read_password(args.password_stdin), user)
    if user.check_password(password):
        raise CommandFailed("choose a password the account has not been using.")
    users.set_password(user, password)
    audit.record("account.password", target=user.get_username())
    print(f"Changed the password of {user.get_username()}; it lasts 30 days.")
    return 0


def named_account(name):
    from .accounts.repositories import AccountRepository

    AccountRepository().adopt_orphans()
    account = AccountRepository().find_by_username(name)
    if account is None:
        raise CommandFailed(f"there is no account named {name!r}.")
    return account


def managed(args, change):
    setup_django(resolve(args), args.database_url)
    from rest_framework.exceptions import APIException

    from .accounts.services import AccountManagementService

    account = named_account(args.name)
    try:
        return change(AccountManagementService(None), account)
    except APIException as exc:
        raise refused(exc) from exc


def command_account_list(args):
    setup_django(resolve(args), args.database_url)
    from .accounts.services import AccountManagementService
    from .accounts.services.account_service import password_max_age

    rows = [
        (
            account.user.get_username(),
            account.role,
            "yes" if account.user.is_active else "no",
            "yes" if account.has_two_factor else "no",
            f"{account.password_changed_at + password_max_age():%Y-%m-%d}",
        )
        for account in AccountManagementService(None).list()
    ]
    headers = ("NAME", "ROLE", "ACTIVE", "TWO-FACTOR", "PASSWORD EXPIRES")
    widths = [max(len(row[index]) for row in (headers, *rows)) for index in range(5)]
    for row in (headers, *rows):
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip())
    return 0


def command_account_role(args):
    def change(service, account):
        if args.role == "master":
            return service.make_master(account.pk)
        return service.set_role(account.pk, args.role)

    account = managed(args, change)
    if account.is_master:
        print(f"{account.user.get_username()} is now the master account.")
    else:
        print(f"{account.user.get_username()} is now {account.role}.")
    return 0


def command_account_disable(args):
    managed(args, lambda service, account: service.set_active(account.pk, False))
    print(f"{args.name} can no longer sign in.")
    return 0


def command_account_enable(args):
    managed(args, lambda service, account: service.set_active(account.pk, True))
    print(f"{args.name} can sign in again.")
    return 0


def command_account_reset(args):
    managed(args, lambda service, account: service.reset_two_factor(account.pk))
    print(
        f"Forgot the two-factor sign-in of {args.name}; it sets it up again at its "
        "next sign-in."
    )
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
    if args.database_url or os.environ.get(DATABASE_URL_ENV):
        return import_into_database(args)
    data_dir = paths.resolve_data_dir(args.data_dir)
    paths.finish_interrupted_import(data_dir)
    passphrase = read_passphrase(args.passphrase_stdin, confirm=False)
    owner = None
    if paths.database_path(data_dir).exists():
        owner = hold_installation(args, data_dir, passphrase)
    from .staging import TransferError, let_go_of, stage_import, stamp, swap_in

    when = stamp()
    try:
        staged = stage_import(args.file, passphrase, data_dir, when)
        if owner is not None:
            let_go_of(data_dir)
        aside = swap_in(staged, data_dir, when)
    except TransferError as exc:
        raise CommandFailed(str(exc)) from exc
    print(f"Imported {staged.records} records into {data_dir}.")
    if aside is not None:
        print(
            f"The installation that was there is now {aside}. DBS never deletes it; "
            f"open it with {PROG} run --data-dir {aside}."
        )
    return 0


def hold_installation(args, data_dir, passphrase):
    setup_django(resolve(args))
    from django.conf import settings

    from .transfer import TransferError, exported_key, manages_servers

    owner = claim_instance()
    if manages_servers() and not args.replace:
        raise CommandFailed(
            "this data directory already manages servers; pass --replace to replace "
            "them. The installation there is moved aside, never deleted."
        )
    try:
        incoming = exported_key(args.file, passphrase)
    except TransferError as exc:
        raise CommandFailed(str(exc)) from exc
    if incoming is not None and incoming != settings.SECRET_KEY:
        confirm_other_key(args, data_dir)
    return owner


def confirm_other_key(args, data_dir):
    if args.yes:
        return
    question = (
        f"The export was sealed with another key than the installation in {data_dir}. "
        "That installation and its key are moved aside, not deleted. Go on? [y/N] "
    )
    if not sys.stdin.isatty():
        raise CommandFailed(
            "the export was sealed with another key than this installation; pass "
            "--yes to move this installation aside and import it."
        )
    try:
        answer = input(question).strip().lower()
    except EOFError:
        answer = ""
    if answer not in ("y", "yes"):
        raise CommandFailed("stopped; nothing was changed.")


def claim_instance():
    from dbs import leases

    owner = leases.process_owner()
    if not take_instance_lease(owner):
        raise CommandFailed(
            "django_dbs run is using this data directory; stop it first."
        )
    return owner


def import_into_database(args):
    if args.replace:
        raise CommandFailed(
            "--replace moves the data folder aside with its database, which needs the "
            f"SQLite database inside it. With ${DATABASE_URL_ENV}, import into an "
            "empty database instead."
        )
    data_dir = resolve(args)
    setup_django(data_dir, args.database_url)
    from dbs import leases

    from .transfer import TransferError, import_manager

    owner = claim_instance()
    try:
        passphrase = read_passphrase(args.passphrase_stdin, confirm=False)
        result = import_manager(args.file, passphrase)
    except TransferError as exc:
        raise CommandFailed(str(exc)) from exc
    finally:
        leases.release(INSTANCE_LEASE, owner)
    print(f"Imported {result.records_loaded} records into {data_dir}.")
    return 0


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


def trusted_proxies(given):
    found = []
    for value in given or ():
        for part in value.split(","):
            if not part.strip():
                continue
            try:
                found.append(str(ipaddress.ip_network(part.strip(), strict=False)))
            except ValueError as exc:
                raise CommandFailed(
                    f"--trusted-proxy takes an address range such as 10.0.0.0/24, "
                    f"not {part.strip()!r}."
                ) from exc
    return found


def exposure(host, proxies, insecure):
    if is_loopback(host):
        return
    if proxies:
        print(
            f"Listening on {host} behind the proxy at {', '.join(proxies)}. Set "
            f"${HOST_ENV} to the name you browse to.",
            file=sys.stderr,
        )
        return
    if insecure:
        print(
            "WARNING: listening on "
            f"{host} over plain HTTP. Anyone on the network path can read passwords, "
            "two-factor codes and sessions. Put a TLS reverse proxy in front and pass "
            "--trusted-proxy instead.",
            file=sys.stderr,
        )
        return
    raise CommandFailed(
        f"listening on {host} would send passwords and sessions over plain HTTP to "
        "anyone who can reach it. Put a TLS reverse proxy in front and pass "
        "--trusted-proxy CIDR with its address range, use an SSH tunnel to "
        "127.0.0.1, or pass --allow-insecure-http if you accept the risk."
    )


def warn_about_key():
    from django.conf import settings

    if settings.DBS_MANAGER_KEY_WARNING:
        print(f"Warning: {settings.DBS_MANAGER_KEY_WARNING}", file=sys.stderr)


def command_run(args):
    proxies = trusted_proxies(args.trusted_proxy) or trusted_proxies(
        [os.environ.get(TRUSTED_PROXY_ENV, "")]
    )
    exposure(args.host, proxies, args.allow_insecure_http)
    data_dir = resolve(args)
    setup_django(data_dir, args.database_url, args.host, proxies)
    from dbs import leases

    from .recovery import recover
    from .runner import get_runner
    from .scheduler import Scheduler

    owner = leases.process_owner()
    if not take_instance_lease(owner):
        return open_running(data_dir, args.no_browser)

    runner = get_runner()
    scheduler = Scheduler()
    server = None
    try:
        recover()
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
        warn_about_key()
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
