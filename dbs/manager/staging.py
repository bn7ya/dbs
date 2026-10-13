from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import conf, keystore, paths

STAGING_MODULE = "dbs.manager.staging"
STAMP_FORMAT = "%Y%m%dT%H%M%SZ"


class TransferError(Exception):
    pass


@dataclass(frozen=True)
class Staged:
    stage: Path
    records: int


def stamp(moment=None):
    return (moment or datetime.now(timezone.utc)).strftime(STAMP_FORMAT)


def stage_import(source, passphrase, data_dir, when):
    stage = paths.staging_path(data_dir, when)
    if stage.exists():
        raise TransferError(f"{stage} already exists; try again in a second.")
    environ = {
        key: value
        for key, value in os.environ.items()
        if key not in (conf.DATABASE_URL_ENV, conf.HOME_ENV)
    }
    environ[keystore.STORE_ENV] = keystore.FILE
    built = subprocess.run(
        [sys.executable, "-m", STAGING_MODULE, str(Path(source).resolve()), str(stage)],
        input=f"{passphrase}\n",
        capture_output=True,
        text=True,
        env=environ,
        check=False,
    )
    if built.returncode != 0 or not paths.import_marker_path(stage).exists():
        if stage.exists():
            shutil.rmtree(stage)
        reason = built.stderr.strip().splitlines()
        raise TransferError(reason[-1] if reason else "the import did not finish.")
    return Staged(
        stage=stage,
        records=json.loads(built.stdout.strip().splitlines()[-1])["records"],
    )


def holds_nothing(folder):
    folder = Path(folder)
    return all(entry.is_dir() and holds_nothing(entry) for entry in folder.iterdir())


def let_go_of(data_dir):
    from django.db import connections

    connections.close_all()
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "baseFilename", "").startswith(str(data_dir)):
            handler.close()
            root.removeHandler(handler)


def swap_in(staged, data_dir, when):
    data_dir = Path(data_dir)
    aside = None
    if data_dir.exists() and holds_nothing(data_dir):
        shutil.rmtree(data_dir)
    if data_dir.exists():
        aside = paths.aside_path(data_dir, when)
        if aside.exists():
            raise TransferError(f"{aside} already exists; nothing was moved.")
        keystore.carry(data_dir, aside)
        os.replace(data_dir, aside)
    os.replace(staged.stage, data_dir)
    keystore.load(data_dir)
    paths.clear_import_marker(data_dir)
    return aside


def main(argv=None):
    source, stage = argv if argv is not None else sys.argv[1:]
    passphrase = sys.stdin.readline().rstrip("\n")
    from .cli import setup_django

    setup_django(paths.ensure_data_dir(Path(stage)))
    from .transfer import import_manager

    try:
        result = import_manager(source, passphrase)
    except TransferError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    paths.write_private(paths.import_marker_path(stage), "")
    print(json.dumps({"records": result.records_loaded}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
