---
name: django-dbs
description: Use when working in a Django project that has django-dbs installed — taking, validating, restoring or scheduling backups, streaming one with dbs backup --stream, the backup schedule, retention, health and hash-chained audit trail in the /admin/dbs/ panel, the session guard, any manage.py dbs command, or the django_dbs manager and its MCP server. Covers the install extras, the passphrase that must never change, restore semantics and the mistakes that lose data.
---

# django-dbs

DBS reads a Django project's models, relations and files and writes one encrypted,
redundant, self-healing file. Every backup stores two copies plus Reed-Solomon parity, so
silent corruption is detected and repaired on restore.

## Installing it

`pip install django-dbs` is the backup library alone. The rest are extras:

| Extra | Adds | Needed for |
|---|---|---|
| `django-dbs[guard]` | scikit-learn | the session guard's anomaly detector |
| `django-dbs[manager]` | djangorestframework, waitress, paramiko, keyring | `django_dbs`, the DBS manager and its MCP server |
| `django-dbs[ssh]` | paramiko | `dbs.transports` |
| `django-dbs[all]` | all three | |

A project that installs `DBSSecurityMiddleware` wants `django-dbs[guard]`. Recommend the
manager extra only on the machine that runs `django_dbs`, never in a project's requirements
for that reason alone.

## Setting it up

```python
INSTALLED_APPS = [..., "django.contrib.admin", "dbs"]
MIDDLEWARE = [..., "django.contrib.auth.middleware.AuthenticationMiddleware", ...,
              "dbs.security.middleware.DBSSecurityMiddleware"]
DBS_BACKUP_DIR = "/var/backups/myproject"
```

```bash
python manage.py migrate
```

`django.contrib.admin` mounts the panel at `/admin/dbs/`; the middleware enforces the
session guard and must sit below `AuthenticationMiddleware` (`manage.py check` warns with
`dbs.security.W002` otherwise). Both are optional — the management commands work without
either — but the guard does nothing at all unless the middleware is installed, so never
describe the panel as guarded in a project that lacks it.

**On any upgrade from 0.2.x, `manage.py migrate` is required**: 0.3.0 added database tables.

## Keep the project current

Whenever you work in a project using django-dbs, run this first:

```bash
python manage.py dbs upgrade --check
```

If it reports outstanding items, resolve them — `python manage.py dbs upgrade` applies the
safe ones — before making other changes. A project that has skipped an upgrade step fails at
runtime, not at install time. After upgrading the package itself, always run `dbs upgrade`.
Pin the version you install (`pip install "django-dbs[guard]==X.Y.Z"`), with the extras the
project uses.

## Never confirm the abandonment of backups

If `dbs upgrade --backups` reports backups it cannot convert, **stop and tell the
developer.** Do not type the confirmation phrase, do not pipe input to the prompt, do not
look for a flag that skips it, and do not delete, move or overwrite any `.dbs` file to get
past it. Those files may be the only copy of data that exists nowhere else, and whether they
still matter is not a judgement you can make.

Report what the command said, including its suggestion to install the older version in a
separate environment and restore from there. Let a human decide.

## The command surface

```bash
python manage.py dbs                      # overview
python manage.py dbs backup OUTPUT [--allow-missing-files] [--database ALIAS]
python manage.py dbs backup --stream [--prefix P] [--output-dir DIR]
python manage.py dbs restore INPUT [--dry-run] [--flush]
python manage.py dbs validate INPUT [--passphrase]
python manage.py dbs schedule [--once]               # follows the panel's schedule
python manage.py dbs schedule --interval 6h --output-dir DIR --keep 5   # a fixed plan
python manage.py dbs health [--json]
python manage.py dbs audit verify
python manage.py dbs connection [--json]
python manage.py dbs key --show
python manage.py dbs security status|unlock USER|retrain|purge
python manage.py dbs ai [--agents] [--check]
python manage.py dbs upgrade [--check] [--self [--to X.Y.Z]] [--backups DIR]
```

`manage.py django-dbs` is the same command under its old name. The original `dbs_backup`,
`dbs_restore`, `dbs_validate` and `dbs_schedule` commands still work and are not deprecated.

`dbs backup PATH` refuses a path that already exists; a script must choose a new name each
run. A missing or unreadable source file stops the backup and names it; only pass
`--allow-missing-files` when the developer accepts a backup without those files.

`dbs backup --stream` writes the backup to standard output and keeps the same bytes in
`DBS_BACKUP_DIR`; its last line on standard error is a JSON summary `{name, size, sha256}`,
with `kept_on_server: true` when standard output broke. It is how the DBS manager takes
backups.

## Passphrases — read this before writing any DBS code

**A project's backup passphrase must never change.** Every backup is encrypted under the
passphrase in force when it was written; change it and every older backup stops opening.
Nobody can open a backup whose passphrase is lost.

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

**Warn the developer** whenever they change `SECRET_KEY`, set or change `DBS_PASSPHRASE`, or
change the passphrase the DBS manager stores for a server: a backup encrypted under a
passphrase they lose, and did not keep in `SECRET_KEY_FALLBACKS`, cannot be opened. Ever.

## Restore semantics — the part that loses data

- A restore **merges** into existing rows by default; an existing row only takes the fields
  the backup carries. `--flush` deletes the rows the backup covers first (children before
  parents, same transaction) so it replaces instead.
- `--dry-run` runs the real load in a transaction it rolls back, writes no files and never
  touches a sequence. It names every file the restore would refuse and exits non-zero when
  there is one. Suggest it before any restore against a database that matters.
- Files are staged beside their targets and moved into place only when the rows commit.
  They land inside `DBS_RESTORE_ROOTS` (or `DBS_FILE_ROOTS`), a `ModelBackup`'s
  `file_roots`, or a file field's storage. For a server whose paths differ,
  `DBS_RESTORE_PATH_MAP = {"/old/root": "/new/root"}`.
- Backups record the applied migration per app. A restore onto a drifted target warns and
  names the apps; rows for unknown models and fields are discarded.
- `--database` restores into that alias, and `dbs backup --database` reads from it.

## Choosing what to back up

DBS backs up every model it finds, minus the defaults it always skips
(`contenttypes.contenttype`, `auth.permission`, `admin.logentry`, `sessions.session`, and
DBS's own records apart from the session guard's policy and known locations) and models
with `managed = False`. A multi-table child brings its parent rows. To configure a model,
register it in an app's `dbs.py`; once anything is registered, only registered models are
backed up:

```python
from dbs import backup_registry, FieldType, ModelBackup
from myapp.models import Invoice

@backup_registry.register(Invoice)
class InvoiceBackup(ModelBackup):
    overrides = {"render_cache": FieldType.EXCLUDE}
```

`DBS_EXCLUDE_MODELS` **extends** the defaults. Prefix a label with `-` to back up a model
the defaults skip, an unmanaged one included, e.g. `["-sessions.Session"]`.

## The admin panel

Mounted automatically at `/admin/dbs/` when `dbs` is in `INSTALLED_APPS` alongside
`django.contrib.admin`. No `urls.py` change. **Superusers only** — there is no grantable
permission for it.

On first login it redirects to a setup wizard that configures the session guard. Every
request through the admin is scored by an IsolationForest; a warning flags the session, which
can then read but not change, download or export anything, and a high enough score ends every
session for that account. Learning mutes only the model, never the rules. Recover with
`python manage.py dbs security unlock USER`.

*Take a backup* and restores run as background jobs on a page that refreshes until they end;
*Take a backup* needs `DBS_BACKUP_DIR`.

The panel keeps backups on the server and pushes nothing anywhere. There are no SFTP targets
and no console; off-site copies come from the DBS manager, which connects over SSH and pulls
them. Never suggest pushing backups from the server, and never add a way to run remote
commands from a browser.

## The schedule, retention, health and audit trail

The backup frequency is a database row edited at `/admin/dbs/backupschedule/`, not a
setting. Turning it on needs `DBS_BACKUP_DIR` and a derivable passphrase. `DBS_SCHEDULER`
picks where it runs: `"thread"` (default, a thread each web worker starts on its first
request, with a database lease so one backup is taken per interval), `"command"` (run
`manage.py dbs schedule` under systemd; with no plan flags it follows the panel) or `"off"`.
Recommend `"command"` behind uWSGI without `--enable-threads`, or when several hosts each
keep their own `DBS_BACKUP_DIR`. `DBS_SCHEDULE_INTERVAL` and `DBS_SCHEDULE_KEEP` seed the
first schedule row; while that schedule is off, a set `DBS_SCHEDULE_INTERVAL` makes
`dbs schedule` run that fixed plan instead.

The server keeps **at most five** backups: the schedule keeps 1 to 5, `dbs schedule`
refuses a larger `DBS_SCHEDULE_KEEP` or `--keep`, and the panel reads a larger
`DBS_SCHEDULE_KEEP` as 5. Retention only touches this
project's `PREFIX-YYYYMMDD-HHMMSSZ.dbs` files (`PREFIX-ALIAS-…` for a database other than
`default`), orders them by recorded time, never counts links, future-stamped or non-DBS
files, and always keeps the newest backup that passed verification.

`manage.py dbs health --json` (and the panel's Health page) grades the last backup's age,
the last validation, the newest file on disk, the backup directory, disk space, the
passphrase and the scheduler. Check it after changing anything about backups.

Every backup, restore, validation, prune, download and panel change writes an `AuditEvent`
with `status`, `data` (file, size, sha256), `error_code` and timings. Finished rows are
sealed in a SHA-256 hash chain; `manage.py dbs audit verify` reports the first broken link.
A backup records the process, never which program started it, and a failing audit write
never fails a backup. Do not add a field that records the caller, and never delete audit
rows.

## The DBS manager

`django_dbs run` (from `django-dbs[manager]`, or `pipx install "django-dbs[manager]"`)
starts a separate local application that manages many servers over SSH. It needs each
server to have django-dbs 0.7 or later, a stable `SECRET_KEY`, `DBS_BACKUP_DIR`, and an SSH
user that owns the project. `manage.py dbs connection --json` prints the details its
add-server wizard reads. The project never contacts the manager. Never put `dbs.manager` in
a project's `INSTALLED_APPS`.

- It **pulls**: each run collects backups waiting on the server under its own name, streams
  a fresh one with `dbs backup --stream`, verifies it, and only then removes the server's
  copies beyond `keep_remote` (0 to 5). It keeps at most five good backups per server and
  plan, never deletes the newest verified one, and quarantines a backup that fails
  verification.
- It stores each server's backup passphrase, sealed. It is captured once, while adding the
  server and before its first backup, and **must never be changed** afterwards.
- Accounts have roles — master, admin, operator, viewer. Web sign-in takes a password and a
  two-factor code; passwords last 30 days. `django_dbs createuser NAME --role ROLE`,
  `django_dbs account list|role|disable|enable|reset-2fa` and `django_dbs password NAME`
  manage them from a shell.
- Everything the interface does is a `django_dbs` command (`server`, `backup`, `plan`,
  `activity`, `env`, `files`, `redeploy`); `django_dbs AREA VERB --help` lists the options.
  Actions guarded by the account password read it with `--password-stdin`; never put a
  password or passphrase in an argument.

`django_dbs mcp` is the MCP server Claude drives. Through it Claude may read everything but
secrets, add servers, take, verify and save backups, add and run plans, keep more backups,
keep `.env` versions and rehearse restores, moves and reverts. It cannot reveal a secret,
restore, move or revert for real, push a `.env`, keep fewer backups, save a file the manager
keeps encrypted, remove or delete anything, or pin a host key a person did not confirm.
When adding a server, show the person the fingerprint from `fingerprint_host` and wait for
them to confirm it on the Servers page or with `django_dbs server confirm-host-key ID`; do
not try to confirm it yourself. When a tool says it needs the account password, tell the
person to do it in the manager.

## Python API

```python
from dbs import create_backup, write_backup, restore_backup, validate_backup

summary = write_backup("backup.dbs", passphrase, using="default")   # streams; BackupSummary
result = restore_backup("backup.dbs", passphrase, dry_run=True, flush=False)
report = validate_backup("backup.dbs", passphrase)
data = create_backup(passphrase)   # the whole backup as bytes, for small projects
```

`write_backup` takes a path that must not exist yet, or any binary file object, and keeps
memory flat. `restore_backup` and `validate_backup` take bytes, a path or a seekable binary
file. `result.files_refused` lists what a dry run would refuse.

Transports (`django-dbs[ssh]`): `from dbs.transports import SSHTarget, push_backup,
pull_backup, open_session`.

## Settings

See `reference/settings.md`. The ones that change behaviour most: `DBS_EXCLUDE_MODELS`,
`DBS_FILE_ROOTS`, `DBS_RESTORE_ROOTS`, `DBS_RESTORE_PATH_MAP`, `DBS_BACKUP_DIR`,
`DBS_SCHEDULER`, `DBS_ANOMALY_ENFORCE`, `DBS_TRUSTED_NETWORKS`, `DBS_TRUSTED_PROXIES`,
`DBS_GEOLOCATION`.

`DBS_SSH_TARGETS`, `DBS_SCHEDULE_PUSH_TARGET`, `DBS_SCHEDULE_KEEP_REMOTE` and
`DBS_ADMIN_CONSOLE_SHELL` were removed with the panel's SFTP targets and console; suggest
deleting them where you find them, and the DBS manager for off-site copies.

## Troubleshooting map

| Symptom | Cause and fix |
|---|---|
| `dbs backup` refuses the output path | It never replaces a file. Choose a new name each run, or let the schedule name them |
| A backup stops naming unreadable files | Restore the files, or pass `--allow-missing-files` if the developer accepts a backup without them |
| Superuser logged out of the admin | The guard scored the request over the logout threshold. `manage.py dbs security unlock USER`, then add the network to the trusted list |
| `/admin/dbs/` returns 404 | Not a superuser, or `django.contrib.admin` is missing from `INSTALLED_APPS` |
| `RestoreError` naming a path | File restores are confined to `DBS_RESTORE_ROOTS` (or `DBS_FILE_ROOTS`). Add the directory, or map the old root with `DBS_RESTORE_PATH_MAP` |
| Restore merged instead of replacing | Pass `--flush`, or tick *Replace instead of merge* in the panel |
| Scheduler exits immediately | It needs `--output-dir` or `DBS_BACKUP_DIR` |
| Scheduled backups never run | `dbs health` says the scheduler has not checked in: no request has reached a worker yet, or uWSGI runs without threads. Use `DBS_SCHEDULER = "command"` and `manage.py dbs schedule` |
| `django_dbs` says it needs `django-dbs[manager]` | `pip install "django-dbs[manager]"` on the machine that runs the manager |
| Manager backups are quarantined | The passphrase the manager stores is not the one the server's backups use. Do not change a passphrase to fix it; tell the developer |

## Testing this project

`pytest`. The session guard scores time of day, so a test that asserts a verdict tier is
time-dependent and will fail at some hours. Set `DBS_TEST_HOUR=3` to run the suite as though
it were 03:00 UTC. Never assert a specific verdict tier without pinning the policy
thresholds first.

## Conventions when editing this project

- Do not compare DBS to other backup tools in code, comments or docs.
- Say "developer", never "end user".
- No comments; docstrings only on the documented public API.
- `pip install django-dbs` must keep working without the extras: code outside
  `dbs/security/`, `dbs/transports/` and `dbs/manager/` imports none of scikit-learn,
  paramiko, djangorestframework, waitress or keyring.
