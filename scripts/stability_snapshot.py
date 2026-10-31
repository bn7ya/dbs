import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tests.stability import (  # noqa: E402
    HERE,
    STABILITY_KEY,
    command_surface,
    documented_settings,
    migration_names,
    parser_tree,
    python_surface,
    route_surface,
)

PARTS = {"library": "tests.settings", "manager": "tests.manager.settings"}
PASSPHRASE = "dbs-stability-golden-passphrase"
PLAINTEXT = "kept since DBS 0.8.0 — محفوظ"
STREAM_BYTES = ("DBS keeps what it sealed. " * 200).encode()
ACCOUNT_ID = 7
TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
RECOVERY_CODE = "abcde-fghjk"
ENV_CONTENT = b"DEBUG=0\nDATABASE_URL=postgres://shop@db/shop\n"
AUTHORS = ("Ada Lovelace", "Grace Hopper", "الحسن بن الهيثم")
TAGS = ("classic", "reference")
BOOKS = (
    ("Notes on the Analytical Engine", "Ada Lovelace", ("classic",), b"0.8.0 cover"),
    ("A-0 System", "Grace Hopper", ("classic", "reference"), None),
    ("كتاب المناظر", "الحسن بن الهيثم", ("reference",), "صورة الغلاف".encode()),
)


def write_new(path, text):
    with open(path, "x", encoding="utf-8") as handle:
        handle.write(json.dumps(text, indent=1, sort_keys=True, ensure_ascii=False) + "\n")


def registry():
    from dbs import BackupRegistry
    from tests.testapp.dbs import BookBackup
    from tests.testapp.models import Author, Book, Tag

    chosen = BackupRegistry()
    chosen.register(Author)
    chosen.register(Tag)
    chosen.register(Book)(BookBackup)
    return chosen


def golden_backup(folder):
    from django.core.files.base import ContentFile

    from dbs import validate_backup, write_backup
    from dbs.container.stream import HEADER_SIZE, StreamReader, schedule
    from tests.testapp.models import Author, Book, Tag

    authors = {name: Author.objects.create(name=name) for name in AUTHORS}
    tags = {label: Tag.objects.create(label=label) for label in TAGS}
    books = []
    for title, author, labels, cover in BOOKS:
        book = Book.objects.create(title=title, author=authors[author])
        book.tags.set([tags[label] for label in labels])
        if cover is not None:
            book.cover.save("golden.txt", ContentFile(cover), save=True)
        books.append(
            {
                "title": title,
                "author": author,
                "tags": sorted(labels),
                "cover": book.cover.name or "",
                "cover_text": cover.decode() if cover is not None else None,
            }
        )
    path = folder / "backup.dbs"
    summary = write_backup(str(path), PASSPHRASE, registry=registry())
    blob = path.read_bytes()
    reader = StreamReader(io.BytesIO(blob))
    slot = reader.layout.slot_size
    damage = [[0, HEADER_SIZE]] + [
        [HEADER_SIZE + position * slot, slot]
        for position, _index, is_first in schedule(reader.blocks, reader.layout.interleave)
        if is_first
    ]
    damaged = bytearray(blob)
    for start, length in damage:
        damaged[start : start + length] = bytes(length)
    if not validate_backup(bytes(damaged), PASSPHRASE).ok:
        raise SystemExit("the damaged golden backup did not heal; choose other damage")
    return {
        "file": path.name,
        "passphrase": PASSPHRASE,
        "sha256": summary.sha256,
        "format_version": summary.format_version,
        "records": summary.records,
        "authors": sorted(AUTHORS),
        "tags": sorted(TAGS),
        "books": books,
        "damage": damage,
    }


def audit_links():
    from dbs.audit import link
    from dbs.models import AuditEvent

    start = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    events = [
        {
            "action": "backup.create",
            "target_name": "backup-20261030-120000.dbs",
            "detail": "",
            "data": {"size": 4096, "sha256": "0" * 64, "models": ["testapp.book"]},
            "status": "succeeded",
            "error_code": "",
            "subject": "",
            "remote_addr": "",
            "succeeded": True,
            "started_at": start.isoformat(),
            "finished_at": (start + timedelta(seconds=3)).isoformat(),
            "created_at": start.isoformat(),
            "chain_index": 1,
        },
        {
            "action": "restore.run",
            "target_name": "backup-20261030-120000.dbs",
            "detail": "تمت الاستعادة",
            "data": {"records": 12},
            "status": "failed",
            "error_code": "restore_failed",
            "subject": "admin",
            "remote_addr": "203.0.113.7",
            "succeeded": False,
            "started_at": (start + timedelta(minutes=5)).isoformat(),
            "finished_at": None,
            "created_at": (start + timedelta(minutes=5)).isoformat(),
            "chain_index": 2,
        },
    ]
    previous = ""
    for event in events:
        fields = {
            name: datetime.fromisoformat(value) if name.endswith("_at") and value else value
            for name, value in event.items()
        }
        previous = link(previous, AuditEvent(**fields))
        event["chain_hash"] = previous
    return events


def library(folder):
    import django

    django.setup()
    from importlib import metadata

    from django.db import connection
    from django.test.utils import override_settings, setup_test_environment

    from dbs.connection import details
    from dbs.crypto.secrets import encrypt_secret
    from dbs.health import report
    from dbs.keys import default_passphrase

    setup_test_environment()
    connection.creation.create_test_db(verbosity=0)
    distribution = metadata.distribution("django-dbs")
    with override_settings(SECRET_KEY=STABILITY_KEY, SECRET_KEY_FALLBACKS=[]):
        vectors = {
            "secret_key": STABILITY_KEY,
            "default_passphrase": default_passphrase(),
            "field_secret": {"plaintext": PLAINTEXT, "token": encrypt_secret(PLAINTEXT)},
        }
    vectors["audit_chain"] = audit_links()
    write_new(
        folder / "library.json",
        {
            "python": python_surface(),
            "commands": command_surface(),
            "outputs": {
                "connection --json": sorted(details()),
                "health --json": sorted(report().as_dict()),
            },
            "settings": documented_settings(),
            "migrations": {"dbs": migration_names("dbs")},
            "console_scripts": sorted(
                entry.name for entry in distribution.entry_points if entry.group == "console_scripts"
            ),
            "extras": sorted(distribution.metadata.get_all("Provides-Extra") or ()),
            "vectors": vectors,
            "backup": golden_backup(folder),
        },
    )


def manager(folder):
    import django

    django.setup()
    from django.test.utils import override_settings

    from dbs.manager import keystore, paths, vault
    from dbs.manager.accounts.services import two_factor_service
    from dbs.manager.backups.services import vault_contexts as backup_contexts
    from dbs.manager.cli import build_parser
    from dbs.manager.envfiles.services import vault_contexts as envfile_contexts
    from dbs.manager.mcp import tools
    from dbs.manager.servers.services import vault_contexts as server_contexts

    sources = {
        f"{module.__name__}.{name}": getattr(module, name)
        for module in (server_contexts, envfile_contexts)
        for name in vars(module)
        if name.isupper()
    }
    service = two_factor_service.TwoFactorService(SimpleNamespace(pk=ACCOUNT_ID))
    with override_settings(SECRET_KEY=STABILITY_KEY, SECRET_KEY_FALLBACKS=[]):
        sealed = {
            source: {"context": context, "token": vault.seal_text(PLAINTEXT, context=context).hex()}
            for source, context in sources.items()
        }
        stream = io.BytesIO()
        vault.seal_stream(io.BytesIO(STREAM_BYTES), stream, context=backup_contexts.SEALED_FILE)
        two_factor = {
            "account_id": ACCOUNT_ID,
            "secret": TOTP_SECRET,
            "sealed_secret": service.sealed(TOTP_SECRET).hex(),
            "recovery_code": RECOVERY_CODE,
            "recovery_digest": service._digest(
                two_factor_service.typed_recovery_code(RECOVERY_CODE)
            ),
        }
        env_fingerprint = vault.fingerprint(ENV_CONTENT, context=envfile_contexts.CONTENT)
    write_new(
        folder / "manager.json",
        {
            "terminal": parser_tree(build_parser()),
            "mcp": {tool.name: tool.input_schema for tool in tools.build(None)},
            "routes": route_surface("dbs.manager.urls"),
            "migrations": {"dbs_manager": migration_names("dbs_manager")},
            "data_folder": {
                "key_file": paths.KEY_FILE.as_posix(),
                "database_file": paths.DATABASE_FILE,
                "instance_file": paths.INSTANCE_FILE,
                "backups_directory": paths.BACKUPS_DIRECTORY,
                "keychain_service": keystore.SERVICE,
            },
            "vectors": {
                "secret_key": STABILITY_KEY,
                "plaintext": PLAINTEXT,
                "sealed": sealed,
                "two_factor": two_factor,
                "env_fingerprint": {
                    "content": ENV_CONTENT.decode(),
                    "fingerprint": env_fingerprint,
                },
                "sealed_file": {
                    "source": f"{backup_contexts.__name__}.SEALED_FILE",
                    "context": backup_contexts.SEALED_FILE,
                    "content": STREAM_BYTES.decode(),
                    "token": stream.getvalue().hex(),
                },
            },
        },
    )


def main():
    parser = argparse.ArgumentParser(
        description="Record what a release promises: its commands, API, settings and "
        "golden files, in tests/stability/VERSION. A recorded release is never rewritten."
    )
    parser.add_argument("version")
    parser.add_argument("--part", choices=sorted(PARTS))
    args = parser.parse_args()
    folder = HERE / args.version
    if args.part:
        os.chdir(REPO_ROOT)
        {"library": library, "manager": manager}[args.part](folder)
        return 0
    folder.mkdir(exist_ok=False)
    with tempfile.TemporaryDirectory() as scratch:
        for part, settings_module in PARTS.items():
            environment = {
                **os.environ,
                "DJANGO_SETTINGS_MODULE": settings_module,
                "DBS_MANAGER_HOME": scratch,
            }
            subprocess.run(
                [sys.executable, __file__, args.version, "--part", part],
                check=True,
                env=environment,
                cwd=REPO_ROOT,
            )
    print(f"Recorded {args.version} in {folder.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
