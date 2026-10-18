from __future__ import annotations

import json
import os
import signal
import sys
import threading
from contextlib import contextmanager, redirect_stdout

from django.core.management.base import BaseCommand, CommandError

from dbs import audit
from dbs._cli import passphrase_source, resolve_passphrase
from dbs.conf import setting
from dbs.crypto.kdf import KDFParams
from dbs.engine import write_backup
from dbs.engine.backup import verify_written
from dbs.exceptions import DBSError
from dbs.naming import DEFAULT_PREFIX, backup_filename, is_backup_name
from dbs.retention import MAXIMUM_KEEP
from dbs.schedule_runner import keep_at_most
from dbs.tee import Progress, TeeSink, sweep_partials

HANGUP_SIGNALS = ("SIGHUP", "SIGPIPE")


@contextmanager
def surviving_a_lost_connection():
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = {}
    for name in HANGUP_SIGNALS:
        number = getattr(signal, name, None)
        if number is not None:
            previous[number] = signal.signal(number, signal.SIG_IGN)
    try:
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def silence(stream) -> None:
    try:
        descriptor = stream.fileno()
    except (AttributeError, OSError, ValueError):
        return
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, descriptor)
    finally:
        os.close(devnull)


class Command(BaseCommand):
    help = "Create a redundant, encrypted DBS backup file."

    def add_arguments(self, parser):
        parser.add_argument("output", nargs="?", help="Path to write the .dbs backup file to; leave out with --stream.")
        parser.add_argument("--passphrase", help="Encryption passphrase; visible to other local processes, prefer $DBS_PASSPHRASE or the interactive prompt.")
        parser.add_argument("--passphrase-stdin", action="store_true", help="Read the passphrase from the first line of standard input.")
        parser.add_argument("--database", default="default", help="Database alias to back up.")
        parser.add_argument("--no-compress", action="store_true", help="Disable zlib compression.")
        parser.add_argument("--no-verify", action="store_true", help="Skip the verify-after-write check.")
        parser.add_argument("--block-size", type=int, default=None, help="Block size in bytes.")
        parser.add_argument("--kdf-time", type=int, default=None, help="Argon2 time cost.")
        parser.add_argument("--kdf-memory", type=int, default=None, help="Argon2 memory cost (KiB).")
        parser.add_argument("--allow-missing-files", action="store_true", help="Back up even when a source file is missing or unreadable, listing what was left out.")
        parser.add_argument("--stream", action="store_true", help="Write the backup to standard output and keep a copy in DBS_BACKUP_DIR; messages go to standard error, the last line a JSON summary.")
        parser.add_argument("--prefix", default=None, help="With --stream: the backup filename prefix; defaults to DBS_BACKUP_PREFIX.")
        parser.add_argument("--output-dir", default=None, help="With --stream: the folder that keeps the copy, instead of DBS_BACKUP_DIR.")
        parser.add_argument("--progress-seconds", type=int, default=0, help="With --stream: name the backup on standard error at once, then report the bytes written every N seconds.")

    def handle(self, *args, **options):
        if options.get("stream"):
            if options.get("output"):
                raise CommandError("--stream writes the backup to standard output; leave out the path.")
        elif options.get("prefix") or options.get("output_dir") or options.get("progress_seconds"):
            raise CommandError("--prefix, --output-dir and --progress-seconds go with --stream.")
        elif not options.get("output"):
            raise CommandError("Give the path to write the backup to, or use --stream.")
        passphrase = resolve_passphrase(
            options.get("passphrase"),
            confirm=True,
            from_stdin=options["passphrase_stdin"],
        )

        kdf_params = None
        if options["kdf_time"] or options["kdf_memory"]:
            base = KDFParams()
            kdf_params = KDFParams(
                time_cost=options["kdf_time"] or base.time_cost,
                memory_cost=options["kdf_memory"] or base.memory_cost,
                parallelism=base.parallelism,
            )

        extra = {}
        if options["block_size"]:
            extra["block_size"] = options["block_size"]

        if options.get("stream"):
            self.stream(passphrase, options, kdf_params, extra)
            return

        output = options["output"]
        skipped_files: list = []
        with audit.track(
            "backup.create",
            target=os.path.basename(output),
            data={"file": os.path.basename(output), "database": options["database"]},
        ) as entry:
            try:
                summary = write_backup(
                    output,
                    passphrase,
                    using=options["database"],
                    compress=not options["no_compress"],
                    verify=not options["no_verify"],
                    kdf_params=kdf_params,
                    allow_missing_files=options.get("allow_missing_files", False),
                    skipped_files=skipped_files,
                    **extra,
                )
            except DBSError as exc:
                raise CommandError(f"Backup failed: {exc}") from exc
            except OSError as exc:
                raise CommandError(f"Cannot write {output}: {exc.strerror or exc}.") from exc
            entry.data.update(
                size=summary.bytes_written,
                sha256=summary.sha256,
                verified=not options["no_verify"],
                compressed=not options["no_compress"],
            )
            audit.record_backup(output, summary.bytes_written, summary.sha256, options["database"])

        source = passphrase_source(
            options.get("passphrase"), from_stdin=options["passphrase_stdin"]
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {options['output']} ({summary.bytes_written:,} bytes), "
                "verified, two redundant copies + Reed-Solomon parity."
            )
        )
        if skipped_files:
            self.stdout.write(
                self.style.WARNING(
                    f"Left out {len(skipped_files)} source file(s) that could not be read: "
                    + "; ".join(skipped_files)
                )
            )
        self.stdout.write(f"Passphrase came from {source}.")

    def stream(self, passphrase, options, kdf_params, extra):
        directory = options.get("output_dir") or setting("DBS_BACKUP_DIR", None)
        if not directory:
            raise CommandError(
                "Set DBS_BACKUP_DIR, or pass --output-dir, so a streamed backup is also "
                "kept on this server."
            )
        directory = os.path.expanduser(str(directory))
        prefix = options.get("prefix") or setting("DBS_BACKUP_PREFIX", DEFAULT_PREFIX)
        if "/" in prefix or not is_backup_name(backup_filename(prefix), prefix):
            raise CommandError(f"{prefix!r} cannot start a backup filename.")
        try:
            output = self.stdout.buffer
        except AttributeError:
            raise CommandError("Standard output does not take bytes.") from None
        sweep_partials(directory)
        with audit.track(
            "backup.create",
            target=prefix,
            data={"database": options["database"], "streamed": True},
        ) as entry, surviving_a_lost_connection(), redirect_stdout(sys.stderr):
            try:
                with TeeSink(output, directory, prefix) as sink, Progress(
                    sink, options.get("progress_seconds") or 0, self.say
                ):
                    summary = write_backup(
                        sink,
                        passphrase,
                        using=options["database"],
                        compress=not options["no_compress"],
                        verify=False,
                        kdf_params=kdf_params,
                        allow_missing_files=options.get("allow_missing_files", False),
                        **extra,
                    )
                    kept = sink.finish(
                        None
                        if options["no_verify"]
                        else lambda partial: verify_written(partial, passphrase, summary)
                    )
            except DBSError as exc:
                raise CommandError(f"Backup failed: {exc}") from exc
            except OSError as exc:
                raise CommandError(f"Cannot keep the backup in {directory}: {exc.strerror or exc}.") from exc
            entry.target = kept.name
            entry.data.update(
                file=kept.name,
                size=kept.size,
                sha256=kept.sha256,
                verified=not options["no_verify"],
                compressed=not options["no_compress"],
            )
            if kept.stream_lost:
                entry.data["kept_on_server"] = True
            audit.record_backup(kept.path, kept.size, kept.sha256, options["database"])
        keep_at_most(directory, prefix, MAXIMUM_KEEP, kept.name)

        if kept.stream_lost:
            silence(output)
            self.say(
                "Standard output closed before the backup was sent; "
                f"it is kept on this server as {kept.path}."
            )
        else:
            self.say(
                f"Streamed {kept.name} ({kept.size:,} bytes), verified, two redundant "
                f"copies + Reed-Solomon parity; also kept as {kept.path}."
            )
        source = passphrase_source(
            options.get("passphrase"), from_stdin=options["passphrase_stdin"]
        )
        self.say(f"Passphrase came from {source}.")
        self.say(json.dumps(kept.as_dict()))

    def say(self, message):
        self.stderr.write(message, style_func=lambda text: text)
