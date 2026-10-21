# DBS 0.8.0 — release notes

Released as a candidate first, `0.8.0rc1`, then as `0.8.0`.

```bash
pip install --upgrade django-dbs   # everything: the library, the guard, SSH and the manager
python manage.py dbs upgrade
```

A server and the Django projects on it are separate things now. The DBS manager adds a server by
its SSH address and finds each application on it from a folder: on the server itself, in a
Compose service or in a container, under Docker or Podman. It backs them up, schedules and
reschedules them, deploys them in place or moves them, keeps their backups on its own machine and
restores them, with a console and a terminal in the browser, so day-to-day work needs neither SSH
nor the Django admin.

The control panel's backups and restores leave the web process for a limited child process.
Large tables are read in pages, a 100 MB row takes DBS about three times its size, and a stream
whose connection broke resumes where it stopped. `pip install django-dbs` installs everything DBS uses,
and the manager answers to `django-dbs`, `django_dbs` and `dbs`.

The full list of changes is in the
[changelog](https://github.com/bn7ya/dbs/blob/main/CHANGELOG.md#080---unreleased).

## Highlights

### Servers and applications

A **server** is an SSH address: its pinned host key, its sealed credentials and the container
engines it has. An **application** is one Django project on it, with where it runs (`host`,
`compose` or `container`; `docker` or `podman`), its paths inside and on the host, its mounts, its
`.env` and where that file lives. Backups, plans, `.env` versions, files, deploys and moves belong
to an application, so one server runs several.

```bash
django_dbs server add web-1 --host 203.0.113.7 --user deploy --key-file ~/.ssh/id_ed25519
django_dbs app add --server web-1 --folder /srv/shop
django_dbs app check shop
```

### An application from a folder

Give the manager a server and a folder. It lists the folder, asks Docker and Podman which
containers belong to it (Compose labels, the working folder, bind mounts), joins the replicas of
one service, finds each container's Python and `manage.py`, asks django-dbs for its settings, maps
container paths to host paths through the mounts and offers the `.env` files Compose and
django-dbs name, best candidate first. Nothing runs in a folder, or a project below it, that
another account can write to. There is no snippet to paste any more: `dbs connection --json` run
inside a container described the container, not the server.

### Docker and Podman

Every command in a container goes through the engine, with the passphrase on standard input. A
restore streams the backup into the container as the container's own user, a `.env` kept in the
image is read and replaced in place, and stale partials and restore leftovers are swept inside the
container, so a taken backup leaves nothing behind on the server. The check reports each engine,
its Compose, and whether the SSH user may use it. The manager never uses `sudo`: an
`engine_permission_denied` is fixed by the engine's group or by rootless Podman.

### Schedules with a first run, a time zone, a pause

A plan has a first run and an IANA time zone, and daily and weekly plans keep their local time
across daylight saving. **Reschedule** moves the next run and the ones after it; **pause** and
**resume** stop and restart a plan, resuming at the next beat after now with no catch-up. All
three are in the interface, the API (`…/reschedule/`, `…/pause/`, `…/resume/`) and the terminal
(`django_dbs plan reschedule|pause|resume`).

### Deploy in place

An application keeps up to twelve deploy steps chosen from a fixed catalogue, each a fixed argument
list with checked names and its own time limit (1 to 120 minutes):

| Step | Runs |
|---|---|
| `git_pull` | `git -C FOLDER pull --ff-only --no-rebase [REMOTE [BRANCH]]`, never prompting |
| `compose_pull`, `compose_build`, `compose_up` | `compose pull`, `compose build [--pull]`, `compose up -d` for the services named |
| `restart` | the Compose service or the container |
| `systemd_user_restart` | `systemctl --user restart UNIT.service` |
| `pip_install` | `PYTHON -m pip install -r FILE`, a file inside the folder |
| `migrate`, `collectstatic` | `manage.py migrate --noinput`, `manage.py collectstatic --noinput` |

A deploy checks the application, takes a safety backup, records its `.env`, runs the steps and
checks again with `manage.py check` and `migrate --check`, recording the git HEAD and the image
before and after. Its rehearsal only reads. A deploy that stopped after a step ran offers its
safety backup back; that restores the data, not the code.

```bash
django_dbs app deploy shop            # a rehearsal
django_dbs app deploy shop --real
```

A **move** to another application, on another server or the same one, works as in 0.7.0.

### A console and a terminal

- **The console** at `/console` runs one `django_dbs` command line as the signed-in account,
  checked against its role like every other request. The commands that read the manager's own disk
  or standard input are not there.
- **The terminal** opens a shell on a server, or inside an application's container or folder, for
  an admin who types the account password each time. It closes on sign-out, a password or role
  change, 15 minutes without input, a minute without a poll or two hours in all; at most four run
  at once, two per account. The audit trail records where, how long and the bytes each way, never
  what was typed or shown. `django_dbs run --terminal master` narrows it to the master and
  `--terminal off` switches it off.

### Transfers that survive

A 0.8 server names the backup it is writing and reports progress every 30 seconds. When the
connection breaks, the manager reconnects after 5, 15 and 45 seconds, waits while the server
finishes, pulls only the rest, and checks the whole digest before it decrypts to verify. A stream
stops early only when nothing arrives for 15 minutes, and a backup has a day in all. A 0.7 server
still works; its broken stream is collected on the next run.

### Every backup in one place

`/backups` lists every application's backups beside the storage each uses. Server copies are
removed once the manager's copy is verified, unless a plan keeps some there.

### Panel jobs in their own process

Backups, restores and scheduled runs from the panel run in `python -m dbs.job_process`, which
reads its job and passphrase from standard input, lowers its priority and stops at its limits. A
child that dies fails its job as `killed` and frees its leases, so a web worker that restarts no
longer takes a backup with it.

| Setting | Default | |
|---|---|---|
| `DBS_JOB_PROCESS` | `True` | `False` keeps jobs in the web process, for hosts that cannot start one |
| `DBS_JOB_TIME_LIMIT` | `"6h"` | Stops the job with `time_limit` |
| `DBS_JOB_MEMORY_LIMIT` | `"2G"` | Stops the job with `memory_limit`; `0` switches it off |
| `DBS_JOB_NICE` | `10` | The child's niceness |
| `DBS_JOB_PYTHON` | this interpreter | For uWSGI, mod_wsgi and other servers whose `sys.executable` is not Python |
| `DBS_JOB_BOOTSTRAP` | `""` | A module that sets Django up, for django-configurations and similar |

A backup that fails for lack of space, a refused folder or a lost database records `disk_full`,
`permission_denied`, `read_only` or `database_failed`.

### Large tables and large values

Rows are read in pages keyed on the primary key, so MySQL no longer buffers a whole table. Models
with binary, text or JSON fields start with one-row pages and grow from the measured row size, and
values of 1 MiB or more are spliced into the frame without copies: backing up or restoring a
100 MB row takes DBS about 3 times its size, down from 5 to 6.5, on top of the copies the database
driver makes itself. On MySQL a backup opens
`REPEATABLE READ` with a consistent snapshot, so every page sees the same moment. The container
format is unchanged; 0.7.0 reads 0.8.0 backups.

### Tested at scale

New suites back up 1,000 tables and a million rows, 100 MB rows, failing backups in real child
processes, a Django site under load during a backup (the CI job publishes the report: throughput,
latency percentiles, errors and memory before, during and after), several instances of one
project sharing a database, two hundred applications in one manager, Docker and rootless Podman
Compose projects over OpenSSH, and an upgrade from a real 0.7.0.

## Upgrading from 0.7.x

### A project

```bash
pip install --upgrade django-dbs
python manage.py dbs upgrade --check   # report only
python manage.py dbs upgrade
```

0.8.0 adds no migration to the `dbs` app. `dbs upgrade` reports each of these:

| Step | What it asks |
|---|---|
| `RetiredExtras` | A requirements file that names `django-dbs[guard]`, `[manager]`, `[ssh]` or `[all]`: write `django-dbs`. The extras still resolve, as empty names, for this release only. |
| `ContribViewsRemoved` | `dbs.contrib` in `ROOT_URLCONF` or `INSTALLED_APPS`: remove it. Use the panel, `dbs backup --stream` or the manager. |
| `CommandNames` | A `Makefile`, `Procfile`, `Dockerfile`, Compose file, shell script or workflow that runs `dbs-upgrade`: write `manage.py dbs upgrade`. |
| `PanelJobProcess` | Whether the panel can start its job process: `DJANGO_SETTINGS_MODULE` set, an interpreter that runs, limits that parse. The remedy names `DBS_JOB_PYTHON` or `DBS_JOB_PROCESS = False`. |
| `MySQLReads` | On MySQL, a `max_allowed_packet` below 64 MiB. |
| `SQLiteWrites` | On SQLite, WAL mode and, on Django 5.1 or later, `"transaction_mode": "IMMEDIATE"`, so the site keeps writing while a backup reads in its own process. |
| `LegacyPartials` | Pre-0.7 `*.dbs.part` files left in `DBS_BACKUP_DIR`, which DBS no longer sweeps; the remedy is the `rm` line. |
| `SSHTargetKeys` | `SSHTarget.from_dict` reads `username` and `key_filename`; the old `user` and `key_file` names are refused. |

**A resolver conflict.** django-dbs now requires `djangorestframework>=3.15,<4`,
`scikit-learn>=1.4.2,<2`, `paramiko>=3.2,<6`, `waitress>=3,<4` and `keyring>=24,<26`. A project
that pins one of them outside that range gets a resolver error from pip; raise the pin. The web
process still imports none of them unless it uses the guard or `dbs.transports`.

### The manager

```bash
pip install --upgrade django-dbs
django_dbs run
```

The manager migrates itself at its next start. Every 0.7 server becomes an application with the
same id, on a new server that carries its SSH address and credentials, so history, plans, backups
and the audit chain stay as they were. Two applications on one machine start on two servers;
**Merge** on the server page joins them when the host, port, user and host key match. On SQLite
the manager first copies its database to `manager.sqlite3.pre-0.8.0` beside it and says so; on
PostgreSQL or MySQL it warns instead, so back that database up before you upgrade.

Every server needs django-dbs 0.7.0 or later; resumed transfers and progress need 0.8.0.

### Going back to 0.7.0

- **A project:** `pip install "django-dbs[guard]==0.7.0"` (0.7.0 names its extras) and add back
  any setting you removed. No migration needs undoing, and 0.7.0 reads every backup 0.8.0 wrote.
- **The manager:** stop it, `pip install "django-dbs[manager]==0.7.0"`, move
  `manager.sqlite3.pre-0.8.0` over `manager.sqlite3` (or restore the database backup you took),
  and start it. Backups it took after the upgrade stay in its backups folder; the old database
  does not list them.

## Removed

- **`dbs.contrib`**, the original in-request backup and restore views.
- The `dbs-upgrade` command alias and the hyphen-alias shim (`manage.py django-dbs` is now a real
  command), `SSHTarget.from_dict`'s `user` and `key_file`, the sweep of pre-0.7 `.part` files, the
  `HiddenRows` upgrade step, `retention.prune_directory`, `prune_remote` and `stale_backups`, and
  the format 1 writers. Format 1 backups still restore, validate and convert.
- The manager's connection snippet and `--runtime compose` on `server add`: `app add --folder`
  finds where an application runs.

## Fixed

- A podman-compose project read as stopped, and its backups as failed.
- A move could restore a backup that failed verification; it now refuses with
  `backup_quarantined`.
- `dbs validate` with a wrong passphrase ended in a traceback; it now says so and exits 1, and
  takes `--passphrase-stdin`.
- The manager's SQLite could fail a job with "database is locked" while another wrote.
- On SQLite with `"transaction_mode": "IMMEDIATE"`, a backup held the write lock while it
  read, so the site's writes waited for it and could fail with "database is locked". It now
  reads in a deferred transaction, and in WAL mode the site keeps writing.

## Security

- The terminal is admin only, asks for the account password for every shell, is bound to the
  browser session that opened it, closes on sign-out, a password or role change, and records no
  keystroke or output. The MCP server and the console never reach it.
- Deploy steps come from a fixed catalogue; no command line or argument list is taken from a
  request, and editing them needs an admin and the account password. The MCP server only
  rehearses a deploy.
- Discovery runs nothing in a folder another account can write to, reads no `.env`, keeps
  only `DJANGO_SETTINGS_MODULE` from a container's environment, and leaves out containers
  whose names could be read as options.
- Adding an application, and changing what it runs (where it runs, its container or Compose
  service, its folders, its Python, its `manage.py` and its settings module), asks for the
  account password at any time, so a stolen session cannot point the manager at a file it
  uploaded. The MCP server adds an application only as discovery found it.
- The manager reads or replaces no `.env` on a server whose folder, or the folder it links
  into, another account can write to.
- The panel still runs no remote command and keeps no SSH credential; its job process reads the
  passphrase from standard input, never its arguments or environment.

[SECURITY.md](https://github.com/bn7ya/dbs/blob/main/SECURITY.md) names the supported versions
(0.8.x), how to report a vulnerability, and the threat model, now with the console, the
terminal, discovery, containers and deploy steps.

## Licenses

DBS is MIT.
[THIRD_PARTY_LICENSES.md](https://github.com/bn7ya/dbs/blob/main/THIRD_PARTY_LICENSES.md) names
the license of every dependency. What changed in this release:

| Package | Now | License |
|---|---|---|
| scikit-learn | required | BSD-3-Clause |
| paramiko | required | LGPL-2.1-or-later |
| djangorestframework, waitress | required | BSD-3-Clause, ZPL-2.1 |
| keyring | required | MIT |
| @xterm/xterm, @xterm/addon-fit | new, bundled in the manager's interface | MIT |
