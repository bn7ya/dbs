---
name: django-dbs
description: Use when working in a Django project that has django-dbs installed — taking, validating, restoring or scheduling backups, configuring SFTP targets, using the /admin/dbs/ panel, the session guard, or any manage.py dbs command. Covers the passphrase model, restore semantics and the mistakes that lose data.
---

# django-dbs

DBS reads a Django project's models, relations and files and writes one encrypted,
redundant, self-healing file. Every backup stores two copies plus Reed-Solomon parity, so
silent corruption is detected and repaired on restore.

## The command surface

```bash
python manage.py dbs                      # overview
python manage.py dbs backup OUTPUT
python manage.py dbs restore INPUT [--dry-run] [--flush]
python manage.py dbs validate INPUT [--passphrase]
python manage.py dbs schedule [--interval 6h] [--once] --output-dir DIR
python manage.py dbs key --show
python manage.py dbs security status|unlock USER|retrain|purge
python manage.py dbs ai [--agents] [--check]
```

`manage.py django-dbs` is the same command under its old name. The original `dbs_backup`,
`dbs_restore`, `dbs_validate` and `dbs_schedule` commands still work and are not deprecated.

## Passphrases — read this before writing any DBS code

The passphrase is **derived from `settings.SECRET_KEY`** by default. There is nothing to
configure. Resolution order:

1. An explicit `--passphrase`, `--passphrase-stdin`, or a form field.
2. The `DBS_PASSPHRASE` environment variable.
3. The `DBS_PASSPHRASE` setting.
4. Derived from `SECRET_KEY`.

Restore and validate also try keys derived from `SECRET_KEY_FALLBACKS`, so a rotation done
the supported Django way does not strand old backups.

**Never** suggest hard-coding a passphrase in `settings.py` or a committed file. **Never**
pass a passphrase as a shell argument in an example — it is visible to other local
processes; use `$DBS_PASSPHRASE` or `--passphrase-stdin`.

**Warn the developer** whenever they change `SECRET_KEY`: a backup encrypted under a key
they lose, and did not keep in `SECRET_KEY_FALLBACKS`, cannot be opened. Ever.

## Restore semantics — the part that loses data

- A restore **merges** into existing rows by default. `--flush` clears the backed-up models
  first (children before parents, same transaction) so it replaces instead.
- `--dry-run` runs the real load in a transaction it rolls back and writes no files. Suggest
  it before any restore against a database that matters.
- Backups record the applied migration per app. A restore onto a drifted target warns and
  names the apps; rows for unknown models and fields are discarded.
- Restoring writes into file storage too. `DBS_RESTORE_ROOTS` bounds where.

## Choosing what to back up

DBS backs up every model it finds, minus the defaults it always skips
(`contenttypes.contenttype`, `auth.permission`, `admin.logentry`, `sessions.session`, and
DBS's own telemetry tables). To narrow it, register in an app's `dbs.py`:

```python
from dbs import backup_registry, ModelBackup
from myapp.models import Invoice

@backup_registry.register
class InvoiceBackup(ModelBackup):
    model = Invoice
```

`DBS_EXCLUDE_MODELS` **extends** the defaults. Prefix a label with `-` to back up a model
the defaults skip, e.g. `["-sessions.Session"]`.

## The admin panel

Mounted automatically at `/admin/dbs/` when `dbs` is in `INSTALLED_APPS` alongside
`django.contrib.admin`. No `urls.py` change. **Superusers only** — there is no grantable
permission for it.

On first login it redirects to a setup wizard that configures the session guard. Every
request through the admin is scored by an IsolationForest; a high enough score ends every
session for that account. Recover with `python manage.py dbs security unlock USER`.

SFTP targets are database rows. Credentials are encrypted at rest under a key derived from
`SECRET_KEY` and never re-displayed. The per-target console runs a fixed allowlist of
provisioning actions; free-form commands need `DBS_ADMIN_CONSOLE_SHELL = True`, which is off
by default because it grants any superuser arbitrary remote command execution from a
browser. Do not enable it casually.

## Python API

```python
from dbs import create_backup, restore_backup, validate_backup

data = create_backup(passphrase, using="default", compress=True, verify=True)
result = restore_backup(data, passphrase, dry_run=True, flush=False)
report = validate_backup(data, passphrase)
```

Transports: `from dbs.transports import SSHTarget, push_backup, pull_backup, open_session`.

## Settings

See `reference/settings.md`. The ones that change behaviour most: `DBS_EXCLUDE_MODELS`,
`DBS_FILE_ROOTS`, `DBS_RESTORE_ROOTS`, `DBS_SSH_TARGETS`, `DBS_BACKUP_DIR`,
`DBS_ANOMALY_ENFORCE`, `DBS_TRUSTED_NETWORKS`, `DBS_ADMIN_CONSOLE_SHELL`, `DBS_GEOLOCATION`.

## Conventions when editing this project

- Do not compare DBS to other backup tools in code, comments or docs.
- Say "developer", never "end user".
- No comments; docstrings only on the documented public API.
- `dbs/client/` must import and run with no Django settings configured. Never import
  `dbs.engine` at client import time, and read settings through `dbs.conf.setting`.
