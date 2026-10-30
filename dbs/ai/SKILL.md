---
name: django-dbs
description: Use when working in a Django project that has django-dbs installed — taking, validating, restoring or scheduling backups, streaming one with dbs backup --stream, the backup schedule, panel jobs and their child process, retention, health and hash-chained audit trail in the /admin/dbs/ panel, the session guard, any manage.py dbs command, or the django_dbs manager (servers and the applications on them, Docker and Podman, deploys, the console and terminal) and its MCP server. Covers the one install, the passphrase that must never change, restore semantics and the mistakes that lose data.
---

# django-dbs

DBS reads a Django project's models, relations and files and writes one encrypted,
redundant, self-healing file. Every backup stores two copies plus Reed-Solomon parity, so
silent corruption is detected and repaired on restore.

## Installing it

`pip install django-dbs` installs everything DBS uses: the backup library, the session
guard's anomaly detector (scikit-learn), the SSH API (paramiko) and the DBS manager
(djangorestframework, waitress, keyring). There are no extras to choose. The names
`django-dbs[guard]`, `[manager]`, `[ssh]` and `[all]` still resolve in 0.8 but add nothing;
write plain `django-dbs` in requirements. A project's web process imports only what it uses,
so the manager's packages never load there.

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
Pin the version you install (`pip install "django-dbs==X.Y.Z"`).

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
python manage.py dbs backup --stream [--prefix P] [--output-dir DIR] [--progress-seconds N]
python manage.py dbs restore INPUT [--dry-run] [--flush]
python manage.py dbs validate INPUT [--passphrase | --passphrase-stdin]
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

`manage.py django_dbs` and `manage.py django-dbs` are the same command as `manage.py dbs`.
The original `dbs_backup`, `dbs_restore`, `dbs_validate` and `dbs_schedule` commands still work
and are not deprecated.

`dbs backup PATH` refuses a path that already exists; a script must choose a new name each
run. A missing or unreadable source file stops the backup and names it; only pass
`--allow-missing-files` when the developer accepts a backup without those files.

`dbs backup --stream` writes the backup to standard output and keeps the same bytes in
`DBS_BACKUP_DIR`; its last line on standard error is a JSON summary `{name, size, sha256}`,
with `kept_on_server: true` when standard output broke. `--progress-seconds N` first names
the backup and its partial file on standard error, then reports the bytes written every N
seconds. It is how the DBS manager takes backups, and resumes one whose connection broke.

`dbs.contrib`, the original in-request backup and restore views, was removed in 0.8.0. If a
URLconf still has `include("dbs.contrib.urls")`, the project will not start: delete the line
and point the developer at `/admin/dbs/` or the DBS manager.

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
change the passphrase the DBS manager stores for an application: a backup encrypted under a
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

Panel backups, panel restores and scheduled backups run in a child process,
`python -m dbs.job_process`, which reads its spec and the passphrase from standard input,
lowers its priority (`DBS_JOB_NICE`, 10) and stops itself at `DBS_JOB_TIME_LIMIT` (`"6h"`) or
`DBS_JOB_MEMORY_LIMIT` (`"2G"`, `0` for none). The job then fails with `time_limit`,
`memory_limit`, or `killed` when the process ended another way; a backup that fails for lack
of space, a folder it may not write, a read-only disk or a lost database records `disk_full`,
`permission_denied`, `read_only` or `database_failed`. Older backups are never touched.
Where the web server embeds Python (uWSGI, mod_wsgi) and the child cannot load the project,
set `DBS_JOB_PYTHON` to the virtualenv's interpreter; `DBS_JOB_BOOTSTRAP` names a callable
that sets Django up instead of `django.setup` (django-configurations: `configurations.setup`);
`DBS_JOB_PROCESS = False` keeps jobs in a web-process thread with no limits. `dbs upgrade`
probes the interpreter and `dbs health` names it. Never move a backup back into the request.

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

`django-dbs run` (also `django_dbs run` or `dbs run`; `pipx install django-dbs` keeps it apart
from a project) starts a separate local application that looks after the Django applications
on many servers over SSH. The project never contacts the manager, and `dbs.manager` never goes
in a project's `INSTALLED_APPS`.

- A **server** is an SSH machine: address, port, user, sealed credentials, the host key a
  person confirmed, and the container engines it has. An **application** is one Django
  project on a server: on the server itself (`host`), in a Compose service (`compose`) or in
  a named container (`container`), under `docker` or `podman`. Backups, plans, `.env`
  versions, files, deploys and moves belong to an application.
- An application is added from a folder: `django_dbs app discover SERVER --folder F` lists
  what it finds, best first, and `django_dbs app add NAME --server SERVER --folder F
  [--candidate N]` adds one and checks it. Discovery matches containers by their Compose
  working folder or a bind mount from the folder, finds the Python and `manage.py`, asks
  `manage.py dbs connection --json`, maps container paths to the server through the mounts
  and offers `.env` candidates. It runs nothing in a folder, or a project below it, that
  another account can write to. The developer never pastes `dbs connection --json` anymore.
- Ask the developer how the project runs, or pass what they said: `--deployment KEY=VALUE` on
  `app discover`, `app add` and `app edit` (`runs_in` host|compose|container, `engine`,
  `database` postgresql|mysql|mariadb|sqlite|other, `database_runs`
  compose|this_server|elsewhere|file, `settings_from` folder_env|compose_env_file|image|environment,
  `source` git|copied|image, `process_manager`, `web_server`). The answers rank discovery and
  change no command; `app show` prints them beside what was found.
- **Moving a server**: `django_dbs server move OLD --to NEW` rehearses carrying every
  application on OLD onto NEW, which may have nothing installed, and lists the packages to
  install, blockers and notes; `--real` asks the account password, NEW's name and the `sudo`
  password of NEW's SSH user, installs what is missing, carries code, `.git`, images, volumes,
  files and `.env`, restores a fresh backup and leaves OLD untouched. `--resume JOB` continues
  a move that stopped. Through MCP, only `rehearse_server_move`.
- Each server needs django-dbs 0.7.0 or later (0.8.0 to resume a broken transfer), a stable
  `SECRET_KEY`, `DBS_BACKUP_DIR` (on a mounted folder in a container), and an SSH user that
  owns the project and, for containers, may run `docker` (the `docker` group) or rootless
  `podman` as itself. Backups and the check never use `sudo`; `engine_permission_denied` means
  the SSH user may not use the engine. Only a server move uses `sudo`, with the password the
  person types for that move.
- It **pulls**: each run collects backups waiting on the server under its own name, streams
  a fresh one with `dbs backup --stream`, verifies it, and only then removes the server's
  copies beyond `keep_remote` (0 to 5). A broken stream from a 0.8 server resumes where it
  stopped. It keeps at most five good backups per application and plan, never deletes the
  newest verified one, and quarantines a backup that fails verification.
- It stores each application's backup passphrase, sealed. It is captured once
  (`django_dbs app capture-passphrase APP`), while adding the application and before its
  first backup, and **must never be changed** afterwards.
- Plans have a first run (`--first-run`), a time zone (`--time-zone`), and can be
  rescheduled (`plan reschedule ID --at WHEN`), paused and resumed.
- **Deploy in place**: an application keeps up to twelve steps from a fixed catalogue —
  `git_pull`, `compose_pull`, `compose_build`, `compose_up`, `restart`,
  `systemd_user_restart`, `pip_install`, `migrate`, `collectstatic` — each a fixed command
  with validated names. A deploy checks the application, takes a safety backup, records its
  `.env`, runs the steps and checks it again; its rehearsal only reads. Never suggest a free
  command line as a deploy step: there is none, by design.
- **The console** (`/console`, `POST /api/console/`) runs one `django_dbs` command line as the
  signed-in account, without the verbs that read the manager's disk or stdin. **The
  terminal** is an interactive shell on a server or inside an application's container, for
  admins only, with the account password every time; it records no keystroke or output.
- Accounts have roles — master, admin, operator, viewer. Web sign-in takes a password and a
  two-factor code; passwords last 30 days. `django_dbs createuser NAME --role ROLE`,
  `django_dbs account list|role|disable|enable|reset-2fa` and `django_dbs password NAME`
  manage them from a shell.
- Everything the interface does is a `django_dbs` command (`server`, `app`, `backup`, `plan`,
  `activity`, `env`, `files`, `redeploy`); `django_dbs AREA VERB --help` lists the options.
  Actions guarded by the account password read it with `--password-stdin`; never put a
  password or passphrase in an argument.

`django_dbs mcp` is the MCP server Claude drives. Through it Claude may read everything but
secrets, add servers, discover, add and check applications, take, verify and save backups,
add and run plans, keep more backups, keep `.env` versions and rehearse restores, moves,
server moves (`rehearse_server_move`), deploys (`rehearse_deploy`) and reverts. It cannot
reveal a secret, restore, move, deploy or revert for real, take a `sudo` password, change deploy steps, push a `.env`, keep fewer backups, save a file the
manager keeps encrypted, remove or delete anything, reach the console or the terminal, or pin
a host key a person did not confirm. When adding a server, show the person the fingerprint
from `fingerprint_host` and wait for them to confirm it on the Servers page or with
`django_dbs server confirm-host-key ID`; do not try to confirm it yourself. When a tool says
it needs the account password, tell the person to do it in the manager.

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

Transports: `from dbs.transports import SSHTarget, push_backup,
pull_backup, open_session`.

## Settings

See `reference/settings.md`. The ones that change behaviour most: `DBS_EXCLUDE_MODELS`,
`DBS_FILE_ROOTS`, `DBS_RESTORE_ROOTS`, `DBS_RESTORE_PATH_MAP`, `DBS_BACKUP_DIR`,
`DBS_SCHEDULER`, `DBS_JOB_PROCESS`, `DBS_JOB_TIME_LIMIT`, `DBS_JOB_MEMORY_LIMIT`,
`DBS_JOB_PYTHON`, `DBS_ANOMALY_ENFORCE`, `DBS_TRUSTED_NETWORKS`, `DBS_TRUSTED_PROXIES`,
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
| `django-dbs` says the installation cannot import a package | `pip install --force-reinstall django-dbs` repairs it |
| The project will not start: `dbs.contrib` not found | 0.8.0 removed it. Delete `include("dbs.contrib.urls")`; backups are taken at `/admin/dbs/` or by the DBS manager |
| A panel job fails with `time_limit`, `memory_limit` or `killed` | It ran past `DBS_JOB_TIME_LIMIT`, used more than `DBS_JOB_MEMORY_LIMIT`, or its process died. Raise the limit or check the server's log; never move the job into the web request |
| Panel jobs cannot start: the interpreter cannot load the project | Set `DBS_JOB_PYTHON` to the project's virtualenv Python, or `DBS_JOB_BOOTSTRAP`; `dbs upgrade` names the interpreter it tried |
| Manager says `engine_permission_denied` | The SSH user may not use Docker or Podman: the `docker` group, or rootless Podman as that user. Never suggest `sudo` for backups |
| Manager backups are quarantined | The passphrase the manager stores is not the one the application's backups use. Do not change a passphrase to fix it; tell the developer |

## Testing this project

`pytest`. The session guard scores time of day, so a test that asserts a verdict tier is
time-dependent and will fail at some hours. Set `DBS_TEST_HOUR=3` to run the suite as though
it were 03:00 UTC. Never assert a specific verdict tier without pinning the policy
thresholds first.

## Conventions when editing this project

- Do not compare DBS to other backup tools in code, comments or docs.
- Say "developer", never "end user".
- No comments; docstrings only on the documented public API.
- `pip install django-dbs` installs every dependency, but code outside `dbs/security/`,
  `dbs/transports/` and `dbs/manager/` still imports none of scikit-learn, paramiko,
  djangorestframework, waitress or keyring, so a project's web process stays light.
