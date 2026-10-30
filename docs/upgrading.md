# Upgrading

From 0.8.0 on, an upgrade keeps every backup opening and everything your project uses working;
[Stability](stability.md) says exactly what stays. Pin the release in your requirements or lock
file, reinstall, and let DBS check the project:

```bash
pip install "django-dbs==X.Y.Z"
python manage.py dbs upgrade
```

`dbs upgrade` is the changelog you can run. It:

- applies pending DBS migrations itself;
- refreshes the AI instructions installed in `.claude/` when they are out of date;
- prints, with the exact line to add, anything that means editing your own code;
- says whether a newer release is on PyPI (`--offline` skips that).

Every run checks the whole project: that `dbs` is installed and migrated, the panel's schedule
and scheduler, the backup folder, the packages DBS imports, the admin panel and the guard's
middleware, forwarded addresses, excluded and unmanaged models, the passphrase, the restore
roots and path map, the backup format, and each release's own steps below.

- `--check` changes nothing and exits non-zero when an item needs you to act, for CI;
  warnings are printed and leave it passing.
- `--self` installs the newest release inside a virtual environment (or `--to X.Y.Z`): it
  prints the pinned `pip install` command and asks first (`--yes` answers for a script), names
  the requirement files to pin it in too, leaves a source checkout alone, and an interpreter
  outside a virtual environment unless you add `--system-python`. Run `dbs upgrade` again
  afterwards to finish.
- `--backups DIR` reads old backups and converts any written in an older format into a new
  file beside the original. Nothing in DBS ever deletes or overwrites a backup.

## From 0.7.x

```bash
pip install --upgrade django-dbs
python manage.py dbs upgrade
```

Backups keep container format 2 and 0.8 adds no migration to projects, so a 0.7 project reads
0.8 backups and the other way round. `dbs upgrade` reports these:

| Step | What it says, and what to do |
|---|---|
| dependencies | `pip install django-dbs` now installs scikit-learn, paramiko, djangorestframework, waitress and keyring. One that cannot be imported is named, with `pip install --force-reinstall "django-dbs"` |
| install extras | A requirement file still names `django-dbs[guard]`, `[manager]`, `[ssh]` or `[all]`: write `django-dbs` without the brackets. The extras add nothing, and keep resolving so an old requirement still installs |
| contrib views | `dbs.contrib`, the original in-request backup and restore views, is gone. Delete `include("dbs.contrib.urls")` from the URLconf it names, and `"dbs.contrib"` from `INSTALLED_APPS`, where it stops Django before this step can run |
| command names | A `Makefile`, `Procfile`, `Dockerfile`, compose file, shell script or workflow still runs `dbs-upgrade`: use `python manage.py dbs upgrade` |
| old partial files | `.part` files left in `DBS_BACKUP_DIR` by a backup before 0.7 are no backups, and DBS no longer sweeps them; the `rm` line removes them |
| panel jobs | Panel backups, restores and scheduled runs now run in a process of their own. The step starts the interpreter DBS will use and checks it loads the project; if not, set `DBS_JOB_PYTHON`, or `DBS_JOB_PROCESS = False` |
| mysql reads | On MySQL, backups read one consistent snapshot; a `max_allowed_packet` below 64 MiB is reported, since a larger value would not restore |
| sqlite writes | On SQLite, a journal mode other than WAL, or deferred transactions on Django 5.1 or later, can make the site's writes fail with "database is locked" while a backup reads; the step prints the `OPTIONS` to set |
| ssh target keys | `SSHTarget.from_dict` reads `username` and `key_filename`: rename `user` and `key_file` |

A project that pins `djangorestframework` below 3.15 meets a resolver conflict, since
django-dbs needs 3.15 or later; raise the pin. Every bundled package is capped below its next
major version.

**The manager** migrates itself the next time any `django_dbs` command starts. Each 0.7 server
becomes a server (its address, credentials and host key) and an application (its project,
paths, passphrase and plans) with the old server's id, so its backups, plans, `.env` versions
and audit rows stay where they were; join servers that are one machine with
`django_dbs server merge`. On SQLite it first keeps a copy of the database as
`manager.sqlite3.pre-0.8.0` beside it and names it at start; on PostgreSQL or MySQL it writes a
warning to `manager.log`, so back that database up before you upgrade. The servers it backs up
need django-dbs 0.7.0 or later, and 0.8.0 to resume a transfer that broke. The wizard no longer
reads a pasted `dbs connection --json`, and `server add` no longer takes `--runtime compose`:
give `app add` the server and the folder.

**Going back to 0.7.** For a project, `pip install "django-dbs[guard]==0.7.0"`, since 0.7
installs the guard's detector only with its extra; 0.8 added no project migration and kept the
backup format, so nothing else changes back. For the manager: stop it,
`pip install "django-dbs[manager]==0.7.0"`, move `manager.sqlite3.pre-0.8.0` back over
`manager.sqlite3` in the data folder (`django_dbs paths` prints it), and start it. Backups the
manager took after the upgrade stay in its backups folder, but the old database does not list
them.

## From 0.6.x

Run `dbs upgrade` as above. It applies the migration that seals the audit trail and drops the
SFTP targets, and reports each of these along with the 0.8 steps:

| Step | What it says, and what to do |
|---|---|
| off-site copies | The panel no longer pushes backups. `DBS_SSH_TARGETS`, `DBS_SCHEDULE_PUSH_TARGET`, `DBS_SCHEDULE_KEEP_REMOTE` and `DBS_ADMIN_CONSOLE_SHELL` do nothing; delete them, and add this server to a DBS manager, which pulls its backups. The SFTP targets the panel held are named in the audit trail |
| dbs-client | `dbs-client` is gone. Install the manager on your own machine and add each server from its config with `django_dbs server add`, then its application with `django_dbs app add` |
| retention | The server keeps at most five backups: a schedule keeping more is lowered to 5, and `dbs schedule` refuses a `DBS_SCHEDULE_KEEP` above 5, which the panel reads as 5 |
| audit chain | The audit trail is sealed in a hash chain; `manage.py dbs audit verify` checks it |
| backup format | New backups are format 2. A `DBS_KDF_TIME_COST` above 10 or `DBS_KDF_MEMORY_COST` above 262144 would make every backup fail; lower them. Convert format 1 backups with `dbs upgrade --backups DIR` |
| forwarded addresses | `DBS_TRUSTED_PROXIES` now lists proxy networks, not a count: `DBS_TRUSTED_PROXIES = ["10.0.0.0/24"]` |
| session guard | `DBSSecurityMiddleware` placed before `AuthenticationMiddleware`: move it below |
| unmanaged models | Models with `managed = False` are left out; list `-app.model` in `DBS_EXCLUDE_MODELS` or register one to keep it |
| missing source files | A missing or unreadable file stops a backup; `--allow-missing-files` backs up without it |
| backup paths | `dbs backup PATH` and `create_backup(output=PATH)` refuse a path that exists; a script that reuses one name must choose a new one each run |
| restore path map | Every new root in `DBS_RESTORE_PATH_MAP` must be inside a restore root |
| remote command limits | SSH connections send keepalives and stop a remote command after 6 hours unless the target sets `command_timeout` |

The manager applies its own migrations the next time any `django_dbs` command starts: its
oldest account becomes the master and every other one an admin; each account sets up
two-factor sign-in at its next web sign-in; plans keep 1 to 5 backups in the manager and 0 to 5
on the server; and every server needs django-dbs 0.7 or later to be backed up.
`django_dbs redeploy start` no longer takes `--archive` or `--migrate`.

## From 0.5.x and 0.4.x

**From 0.5.x:** `dbs schedule` with no flags now follows the panel, unless
`DBS_SCHEDULE_INTERVAL` is still set. While the panel's schedule is off, the command waits for
it instead of backing up every 24 hours; turn the schedule on, or pass `--interval`.
`dbs upgrade` says so when it applies. The manager applies its own new migrations the next time
any `django_dbs` command starts.

**From 0.4.x:** `dbs upgrade` applies the audit and schedule migrations. If you set
`DBS_SCHEDULE_INTERVAL`, turn the schedule on once in the panel, or keep running
`dbs schedule --interval …` as before. Projects behind uWSGI without threads should set
`DBS_SCHEDULER = "command"`.
