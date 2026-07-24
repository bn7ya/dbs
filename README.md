# DBS — Django Backup Solution

> 🚧 **Under development.** DBS is in active development and its API may change.
>
> Created by **Sudum Technology — Research and Development sector**.
> Our very tiny contribution to this world.

A backup library you drop into a Django project's source. It reads your models,
relations and files and writes **one encrypted file** that is *redundant* and
*self-healing*: every backup stores **two copies** of the data plus
**Reed-Solomon parity**, so silent corruption — the kind a non-ECC RAM stick
produces — is detected and repaired on restore instead of quietly poisoning
your data.

```
io  ──►  security (Argon2id + AES-256-GCM)  ──►  integrity (2 copies · per-block
hashes · Reed-Solomon)  ──►  data (models · relations · files)
```

## Features

* **Two self-healing copies in one file** plus Reed-Solomon parity for bit-rot.
* **Per-field mapping**: value, embedded file, or file-path.
* **Passphrase-derived key, never stored** (Argon2id).
* **Per-file and per-block integrity hashes.**
* CLI · admin-UI download · SFTP.

## Install

```bash
pip install django-dbs          # core
pip install "django-dbs[ssh]"   # + SFTP transport (paramiko)
```

Add the app:

```python
INSTALLED_APPS = [..., "dbs"]
```

## Quick start

### 1. (Optional) declare what to back up

By default DBS auto-discovers every model, treats `FileField`/`ImageField` as
files, and preserves relations. Register a model only to override the defaults —
in a `dbs.py` module inside your app (auto-discovered like `admin.py`):

```python
# myapp/dbs.py
from dbs import backup_registry, FieldType, ModelBackup
from .models import Invoice

@backup_registry.register(Invoice)
class InvoiceBackup(ModelBackup):
    overrides = {
        "scanned_pdf_path": FieldType.FILE_PATH,  # CharField holding a path -> embed the file
        "render_cache": FieldType.EXCLUDE,        # don't back this column up
    }
    file_roots = ["/srv/myapp/uploads"]           # extra non-model file trees
```

`FieldType` values: `VALUE` (default), `FILE` (embed a FileField's bytes),
`FILE_PATH` (a string column whose path's file is embedded), `EXCLUDE`.

### 2. Back up / restore / validate from the CLI

```bash
python manage.py dbs_backup   backup.dbs            # prompts for a passphrase
python manage.py dbs_validate backup.dbs            # structural check, no passphrase
python manage.py dbs_validate backup.dbs -p secret  # + verify decryption
python manage.py dbs_restore  backup.dbs            # restore rows + files
```

The passphrase comes from `--passphrase`, then `$DBS_PASSPHRASE`, then a prompt.

### 3. Download / upload from the admin UI

```python
# urls.py
urlpatterns += [path("dbs/", include("dbs.contrib.urls"))]
```

Superusers can then visit `/dbs/backup/` to download an encrypted backup and
`/dbs/restore/` to upload one. The passphrase is entered in the form and never
stored server-side.

### 4. Ship a backup to another server (SFTP)

```python
# settings.py — profiles reference a key by path; no secrets embedded
DBS_SSH_TARGETS = {
    "offsite": {
        "host": "backups.example.com", "username": "deploy",
        "key_filename": "/home/deploy/.ssh/id_ed25519",
        "remote_dir": "/var/backups/myproject",
        "known_hosts": "/home/deploy/.ssh/known_hosts",
    }
}
```

```python
from dbs import create_backup
from dbs.transports import SSHTarget, push_backup

data = create_backup("my passphrase")
push_backup(data, "backup.dbs", SSHTarget.from_settings("offsite"))
```

### Python API

```python
from dbs import create_backup, restore_backup, validate_backup

blob = create_backup("passphrase", output="backup.dbs")
report = validate_backup(blob, "passphrase")   # report.ok / report.summary()
result = restore_backup(blob, "passphrase")    # result.healed is True if it repaired corruption
```

## How it heals

On write, the encrypted stream is split into blocks; each block gets a BLAKE2b
hash and a layer of Reed-Solomon parity, and the whole stream is stored **twice**
(plus the header and manifest are stored twice). On read, each block is taken
from whichever copy verifies; sparse bit-flips are corrected in place by
Reed-Solomon even when *both* copies are hit. Every recovered block is checked
against its stored hash, so a mis-correction can never slip through — and a
freshly written backup is re-read and verified end-to-end (**verify-after-write**)
before the command reports success.

What it can recover from: whole-block loss in one copy, and sparse byte errors
(up to the parity budget, ~8 bytes per 255-byte codeword by default) in both
copies. What it cannot: a block destroyed *beyond* the parity budget in **both**
copies — DBS then refuses to restore and reports exactly which blocks failed,
rather than producing silently wrong data.

## Security model

* **Argon2id** derives a key from your passphrase (memory-hard ⇒ brute-force
  resistant). Raise `KDFParams` cost for more resistance.
* **Envelope encryption**: a random data key encrypts the payload with
  **AES-256-GCM**; that data key is wrapped by the passphrase-derived key. The
  file stores only the salt, Argon2 parameters and the wrapped key — **never the
  passphrase and never the raw data key**.
* A wrong passphrase fails the GCM tag check and is reported as such; it can
  never yield partial/garbage data.

## Restore semantics

* The database load runs in a **single transaction**: if anything fails midway,
  every row is rolled back and the database is left untouched.
* Backup collection also runs in a transaction, so a backup is a consistent
  snapshot even while the application keeps writing.
* Writing a `.dbs` file is **atomic and durable** (temp file + fsync + rename),
  and verify-after-write re-reads the bytes that actually landed on disk.
* File restores are **confined**: `FILE_PATH` and file-root entries are only
  written when the target resolves under a directory listed in
  `DBS_RESTORE_ROOTS` (or, if unset, `DBS_FILE_ROOTS`). Anything else raises
  `RestoreError`. Configure the allow-list before restoring backups that embed
  external files.
* Restoring merges by primary key into the target database; rows created after
  the backup was taken are not deleted.

## Observability

DBS logs to the `dbs` logger: backup/restore start and finish, skipped source
files, SFTP transfers, and — most importantly — a `WARNING` whenever silent
corruption was detected and healed. Route that logger to your monitoring so a
degrading disk is noticed before both copies are damaged:

```python
LOGGING = {
    "version": 1,
    "loggers": {"dbs": {"handlers": ["console"], "level": "INFO"}},
}
```

Files that could not be read during a backup are also recorded in the
manifest (`validate_backup(...).stats["skipped_files"]`).

## Settings reference

| Setting | Purpose |
|---|---|
| `DBS_EXCLUDE_MODELS` | `["app.Model", ...]` to skip (defaults skip contenttypes, permissions, admin log, sessions). |
| `DBS_FILE_ROOTS` | Extra directories embedded in every backup. |
| `DBS_RESTORE_ROOTS` | Directories file restores may write into (falls back to `DBS_FILE_ROOTS`). |
| `DBS_SSH_TARGETS` | Named SFTP connection profiles. |
| `DBS_MAX_UPLOAD_BYTES` | Admin restore upload size cap (default 1 GiB). |
| `DBS_MAX_PAYLOAD_BYTES` | Decompressed payload size cap on restore (default 4 GiB). |
| `DBS_KDF_TIME_COST` / `DBS_KDF_MEMORY_COST` / `DBS_KDF_PARALLELISM` | Default Argon2id cost parameters for new backups. |

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT
