# DBS — Django Backup Solution

> 🚧 **Under development.** DBS is in active development and its API may change.
>
> Created by **Sudum Technology — Research and Development sector**.
> Our very tiny contribution to this world.

DBS backs up a Django project into **one encrypted file**: rows, relations and files
together. The file is *redundant* and *self-healing*. It holds **two copies** of your data
plus **Reed-Solomon parity**, so silent corruption is detected and repaired when you
restore, instead of quietly poisoning the data you were relying on.

## One package, four ways to use it

```bash
pip install django-dbs
```

That installs everything DBS uses: the backup library, the session guard's anomaly detector
(scikit-learn), the SSH API (paramiko) and the DBS manager (djangorestframework, waitress
and keyring). What you get depends on where you use it:

| You… | You get |
|---|---|
| add `"dbs"` to a project's `INSTALLED_APPS` | **The backup library** — `manage.py dbs backup / restore / validate` |
| …and open `/admin/dbs/` as a superuser | **The panel** — backup frequency, restore, health and a tamper-evident audit trail, behind the session guard |
| run `django_dbs run` on your own machine | **The DBS manager** — a local app that looks after the Django applications on your servers, whether they run on the server itself, in a Compose service or in a container, under Docker or Podman. It finds them from a folder, pulls and schedules their backups, restores them, deploys them in place or moves them, and opens a console and a terminal in the browser. Every action is also a command: `django_dbs app add`, `django_dbs backup take --all` |
| run `claude mcp add dbs -- django_dbs mcp` | **Claude at the controls** — ask Claude to add your servers and applications, take and verify backups, set up plans and rehearse restores and deploys. It never sees a secret and cannot restore, deploy or delete anything for real |

The manager's command has three names: `django-dbs`, `django_dbs` and `dbs` all start it, so
`django-dbs run`, `django_dbs run` and `dbs run` are the same. Inside a project,
`manage.py dbs`, `manage.py django_dbs` and `manage.py django-dbs` are one command too.

A project's web process imports only what it uses: the manager's packages never load there,
and scikit-learn loads only for the guard. On the machine that runs the manager,
`pipx install django-dbs` keeps it in an environment of its own. The `[guard]`, `[manager]`,
`[ssh]` and `[all]` extras of earlier releases still resolve in 0.8 but add nothing; write
plain `django-dbs` in your requirement files, and `manage.py dbs upgrade` names any file that
still has the brackets.

The manager needs nothing else on its machine: no Node, no Docker, no Redis, no separate
database server.

**Contents:**
[In your Django project](#1-in-your-django-project) ·
[The panel](#2-the-panel-at-admindbs) ·
[The DBS manager](#3-the-dbs-manager) ·
[Docker and Podman](#docker-and-podman) ·
[Console and terminal](#the-console) ·
[Claude and MCP](#let-claude-control-the-manager) ·
[Deploying and moving](#deploying-and-moving) ·
[Restoring](#restoring) ·
[Passphrases](#passphrases) ·
[Command reference](#command-reference) ·
[Settings reference](#settings-reference) ·
[Upgrading](#upgrading)

---

## 1. In your Django project

### What the project needs

DBS runs inside your project, so it asks only for what a well-run Django project already
has. Keep these in a `.env` file next to `manage.py` (and out of version control):

```ini
# .env
DJANGO_SECRET_KEY=a-long-random-string-that-never-changes
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=example.com

DBS_BACKUP_DIR=/var/backups/myproject
# DBS_PASSPHRASE=only-if-you-want-a-passphrase-other-than-the-derived-one
# DBS_SCHEDULER=thread
```

| Requirement | Why |
|---|---|
| A **stable `SECRET_KEY`** | DBS derives the backup passphrase from it, and **a project's backup passphrase must never change**: older backups would no longer open. Rotate `SECRET_KEY` only with the old value kept in `SECRET_KEY_FALLBACKS`. |
| **`DBS_BACKUP_DIR`**, writable by the app | Where backups are kept — at most five — and where the panel restores and checks them from. The DBS manager pulls its copies from here. |
| `django.contrib.admin` mounted | The panel lives inside the admin. |
| A superuser | The panel is for superusers only. |
| Python 3.9+ and Django 4.2 to 6.x | |

```bash
pip install django-dbs
```

Read them in `settings.py` — the standard library is enough:

```python
# settings.py
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

for line in (BASE_DIR / ".env").read_text().splitlines() if (BASE_DIR / ".env").exists() else []:
    key, _, value = line.partition("=")
    if key.strip() and not key.lstrip().startswith("#"):
        os.environ.setdefault(key.strip(), value.strip())

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = os.environ.get("DJANGO_DEBUG", "false") == "true"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # your apps…
    "dbs",
]

MIDDLEWARE = [
    # Django's defaults, AuthenticationMiddleware among them…
    "dbs.security.middleware.DBSSecurityMiddleware",
]

DBS_BACKUP_DIR = os.environ.get("DBS_BACKUP_DIR", str(BASE_DIR / "backups"))
DBS_SCHEDULER = os.environ.get("DBS_SCHEDULER", "thread")
```

`DBSSecurityMiddleware` goes below `AuthenticationMiddleware`: above it, the guard never sees
who is signed in, and `manage.py check` says so. `DBS_PASSPHRASE` is read straight from the
environment by DBS, so it needs no line in `settings.py`. If you already use
`django-environ` or `python-dotenv`, use them instead of the loop above.

```python
# urls.py — the admin you already have; DBS needs nothing more
from django.contrib import admin
from django.urls import path

urlpatterns = [path("admin/", admin.site.urls)]
```

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py dbs upgrade      # checks everything above and says what is missing
```

### Take, check and restore a backup

```bash
python manage.py dbs backup backup.dbs                  # write an encrypted backup
python manage.py dbs validate backup.dbs --passphrase   # check blocks and decryption
python manage.py dbs restore backup.dbs --dry-run       # rehearse; changes nothing
python manage.py dbs restore backup.dbs                 # restore for real
```

No passphrase to invent: DBS derives one from `SECRET_KEY`. Run
`python manage.py dbs key --show` once and keep the result somewhere safe.

`dbs backup` never replaces a file. It refuses a path that already exists, writes the backup
beside it, readable by its owner alone, verifies it end to end and only then moves it into
place. A source file that is missing or unreadable stops the backup and names the file;
`--allow-missing-files` backs up without it and lists what was left out.

Backups stream. Rows are read in batches from one database snapshot and files in chunks,
while other threads compress, encrypt, add parity and write, so memory stays flat however
large the project grows. A restore reads the file the same way.

### Large tables and large values

Rows are read in pages keyed on the primary key, at most 500 rows or 8 MiB a page, so no
database driver holds a whole table in memory. A model with binary, text or JSON fields
starts with one row a page and grows the page from the row size it measures, and a value of
1 MiB or more goes into the backup without being copied again, so backing up or restoring a
100 MB row takes DBS about three times its size, on top of the copies the database driver
makes itself. One row may be up to 256 MiB.

On PostgreSQL and MySQL a backup reads inside one `REPEATABLE READ` transaction, on MySQL
started `WITH CONSISTENT SNAPSHOT`, so every page sees the same moment while the site keeps
writing. A table that holds values larger than MySQL's `max_allowed_packet` cannot be
restored there; `manage.py dbs upgrade` warns when it is below 64 MiB. On SQLite, WAL mode
lets the site keep writing while a backup reads, and `dbs upgrade` prints the `OPTIONS` that
turn it on.

### A backup on standard output

```bash
python manage.py dbs backup --stream > /mnt/elsewhere/backup.dbs
```

`--stream` writes the backup to standard output and keeps the same bytes in
`DBS_BACKUP_DIR` (or `--output-dir`), named `PREFIX-YYYYMMDD-HHMMSSZ.dbs` with
`DBS_BACKUP_PREFIX` (or `--prefix`). Messages go to standard error, and its last line is a
JSON summary: `{"name", "size", "sha256"}`. When standard output breaks mid-way, the backup
still finishes on the server, the command exits 0 and the summary adds
`"kept_on_server": true`. The server keeps at most five streamed backups per prefix.

`--progress-seconds N` adds a first line on standard error that names the backup and its
partial file, `{"progress": {"name", "partial", "moment"}}`, then
`{"progress": {"bytes": n}}` every N seconds. This is how the DBS manager takes a backup: it
knows which file to wait for if the connection breaks, and resumes from where it stopped.

---

## 2. The panel at `/admin/dbs/`

Once `dbs` is installed alongside `django.contrib.admin` and you have run `migrate`, the
panel is at **`/admin/dbs/`**. There is no `urls.py` change to make.

| Page | What it does |
|---|---|
| Dashboard | Schedule, health, recent backups and the guard at a glance |
| **Schedule** | Turn scheduled backups on, set how often and how many to keep, 1 to 5 |
| **Health** | Is the last backup recent enough, valid, still on disk? Is there disk space and a passphrase? Do panel jobs get a process of their own? |
| **Audit** | Every backup, restore, validation, prune, download and change made in the panel, sealed in a hash chain |
| Backups | Every backup this project wrote; **download** or **restore** any one kept in `DBS_BACKUP_DIR` |
| Take a backup | Writes one to `DBS_BACKUP_DIR` in the background, then offers it for download |
| Restore | Upload a `.dbs` file, with a dry run that changes nothing |
| **Connection** | What to give a DBS manager — the server's SSH address and the project's folder — and, when the project runs in a container, which folder on the server that is |
| Security · Wiki | The session guard, and the full manual |

**Superusers only.** There is deliberately no grantable permission for it: the panel can
download and overwrite your entire database. On your first visit a short wizard asks which
networks you log in from and how strict the guard should be.

Backups stay on this server. The panel pushes nothing anywhere: off-site copies are the DBS
manager's job, which connects to this server and pulls backups to its own machine (see
[Off-site copies](#off-site-copies)).

### Backup frequency

Open **Schedule**, tick *enabled*, and pick an interval (`30m`, `6h`, `1d`) and how many
backups to keep, from 1 to 5 (5 by default). That is all: the schedule runs inside your web
workers. On the first request a worker serves, a small background thread starts and checks
once a minute whether a backup is due. Every worker runs one, and a lease in the database
makes sure exactly one backup is taken per interval however many workers or servers you run.

The lease lasts two minutes and is renewed every 30 seconds while a backup runs, so a long
backup is never started twice. A run is recorded in the audit trail as running before it
starts. If its worker dies, the row is marked interrupted and the next tick takes the backup
again; if that one dies too, the schedule waits for the next interval.

Prefer a separate process? Set `DBS_SCHEDULER = "command"` and run
`python manage.py dbs schedule` under systemd. It follows the same panel setting. Set
`DBS_SCHEDULER = "off"` to switch scheduling off entirely.

| Deployment | Use |
|---|---|
| gunicorn, uWSGI with `--enable-threads`, Daphne, uvicorn | `"thread"` (default) |
| uWSGI without threads, or several hosts each with its own local `DBS_BACKUP_DIR` | `"command"`, one `dbs schedule` process |
| Serverless, or backups taken only from a DBS manager | `"off"` |

When a DBS manager takes this project's backups too, its check warns that the panel's
schedule is also on; turn one of them off, or plan fewer backups in the manager.

### What is kept

The server keeps at most five backups in `DBS_BACKUP_DIR`. After each scheduled or panel
backup, retention removes the oldest of this project's backups beyond the schedule's number,
and only those:

* It only touches files named for this project and database:
  `backup-YYYYMMDD-HHMMSSZ.dbs` for the `default` database and
  `backup-ALIAS-YYYYMMDD-HHMMSSZ.dbs` for any other, with `DBS_BACKUP_PREFIX` in place of
  `backup`. Two backups taken in the same second get `-2`, `-3` and so on, never the same
  name. Anything else in the folder is left alone.
* Backups are ordered by the time recorded when they were taken, then the time written inside
  the file, and only then by name.
* A name stamped in the future, a link, or a file that is not a DBS backup is never counted
  and never removed.
* The newest backup that passed verification is always kept, and a backup that failed
  verification never takes one of the places.

Unfinished temporary files older than an hour are cleared from the folder.
`dbs backup PATH` removes nothing; `dbs backup --stream` keeps at most five per prefix.

### Taking a backup and restoring from the panel

*Take a backup*, restoring a stored backup and restoring an upload run in the background,
outside the web request, so a worker timeout never cuts one short. The page you land on
refreshes every few seconds until the job ends, then shows the outcome, with a download link
for a finished backup. Only one backup or restore runs at a time. *Take a backup* needs
`DBS_BACKUP_DIR`; a download only ever streams a file already written there.

Every backup in `DBS_BACKUP_DIR` has a **restore** link on its row. The page opens with
*Dry run* ticked; a real restore needs the file name typed out. *Replace instead of merge*
clears the backed-up rows first. See [Restoring](#restoring) for what a restore does.

### Panel jobs run in a process of their own

A panel backup, a panel restore and a scheduled backup each run in a child process,
`python -m dbs.job_process`, never in the web worker that served the request. The child reads
what to do, passphrase included, from its standard input, never from its arguments or its
environment; it lowers its priority, holds the job's leases, and stops itself when it runs
too long or uses too much memory. The worker that started it watches it, and if the child
dies the job fails, its leases are freed and its partial file is removed. A backup never
holds memory or a thread of the web process.

| Setting | Default | |
|---|---|---|
| `DBS_JOB_TIME_LIMIT` | `"6h"` | How long a job may run, as `30m`, `6h` or `1d` |
| `DBS_JOB_MEMORY_LIMIT` | `"2G"` | How much memory a job may use, as `512M` or `2G`; `0` for no limit |
| `DBS_JOB_NICE` | `10` | How much the child lowers its priority |
| `DBS_JOB_PYTHON` | the project's Python | The interpreter that runs the child |
| `DBS_JOB_BOOTSTRAP` | `django.setup` | A dotted path to the callable that sets Django up in the child, such as `configurations.setup` for django-configurations |
| `DBS_JOB_PROCESS` | `True` | `False` runs jobs in a thread of the web process, with no time or memory limit |

A job that is stopped fails with `time_limit` or `memory_limit`, and one whose process ended
any other way with `killed`; the job page says which. A backup that fails for lack of space,
a folder it may not write, a read-only disk or a lost database connection records
`disk_full`, `permission_denied`, `read_only` or `database_failed`. Older backups are never
touched and retention does not run after a failure.

The child starts with the same `DJANGO_SETTINGS_MODULE`, working folder and `sys.path` as
the worker. Where the web server embeds Python — uWSGI, mod_wsgi — DBS uses the `python3`
of the environment it runs in, so set `DBS_JOB_PYTHON` to the project's virtualenv Python
when that is not the one. `manage.py dbs upgrade` starts one such interpreter, checks that it
can load the project, and says what to set when it cannot; `manage.py dbs health` names the
interpreter and the limits.

### Health

**Health** grades each check `ok`, `info`, `warn` or `error`:

* the last backup's age against the schedule: fine up to 1.5× the interval, late up to 3×,
  failing beyond that;
* the last validation, and whether the newest backup file is still on disk;
* whether `DBS_BACKUP_DIR` is writable and has room for two more backups;
* whether a passphrase is available for unattended backups;
* whether panel jobs run in their own process, with which interpreter and limits;
* when the scheduler last checked in, and the most recent failure.

`python manage.py dbs health` prints the same report; `--json` gives it to a monitoring
system, with the panel's schedule (`enabled`, `interval_seconds`, `keep`, `mode`).

### The audit trail

Each backup, restore, validation, retention prune, download, export and schedule change
writes one row: what happened, to which file, its size and SHA-256, how long it took and
whether it succeeded, with an error code when it did not. Every change made in the panel is
recorded too, under the superuser who made it. A backup records itself the same way however
it was started — the panel, the schedule, `manage.py`, cron or an SSH session — so the trail
describes the process, never which program asked for it. Writing the trail can never fail a
backup: if the database refuses the row, the backup still completes and the problem is
logged.

The trail is tamper-evident. Once a row finishes it is sealed with the SHA-256 of the row
before it and its own content, so a row changed or deleted afterwards breaks the chain there:

```bash
python manage.py dbs audit verify
```

It prints the first broken link, or the head of the chain, which you can keep somewhere else
to compare later. No DBS command deletes audit rows.

---

## 3. The DBS manager

The manager is a small application that runs on your own machine (or any machine you
choose) and looks after the Django applications on your servers. It connects to them over
SSH and:

* **finds an application from a folder** — on the server itself, in a Compose service or in a
  container, under Docker or Podman;
* **pulls their DBS backups**, on demand or on a plan, resuming a transfer that broke, and
  keeps the newest five of each;
* **backs up folders** as encrypted archives and **collects files** they already make;
* **browses their files** inside the folders you allow;
* **keeps every version of their `.env`**, encrypted, and can put one back;
* **restores a backup onto any application** — its own or another;
* **deploys an application in place**, from a fixed list of steps, after a safety backup;
* **moves an application to another**, and puts it back if a move stops;
* **runs its own commands in a console** and **opens a terminal** on a server or inside a
  container, in the browser;
* **records every action** in its own audit trail, under the account that acted.

It is English and Arabic, right-to-left included.

### Start it

```bash
pip install django-dbs      # or: pipx install django-dbs
django_dbs run              # or: django-dbs run, or dbs run
```

If the shell says `django_dbs` is not recognized, pip put the script in a folder that is not
on your `PATH`. Run `python -m dbs.manager run` instead, or install it with pipx. If an
installation cannot import a package it brought, `django_dbs` names it and prints the
`pip install --force-reinstall "django-dbs"` line that repairs it.

The first run creates a data folder, a local SQLite database and a sealing key, starts the
manager on `http://127.0.0.1:8765` and opens your browser at a one-time setup page. Choose
the username and password of the **master account**, then set up two-factor sign-in: scan
the QR code with an authenticator app, type the code it shows, and keep the ten recovery
codes somewhere safe. The next `django_dbs run` opens straight to the sign-in page. Running
it again while it is already running just opens the browser on the running one.

| Option | Meaning |
|---|---|
| `--port 8765` | Port to listen on. If it is taken, a free one is chosen |
| `--host 127.0.0.1` | Address to listen on. Anything but loopback needs `--trusted-proxy` or `--allow-insecure-http` |
| `--trusted-proxy CIDR` | The address range of the TLS reverse proxy in front of the manager. Repeat for more |
| `--allow-insecure-http` | Listen beyond this computer over plain HTTP, accepting that passwords cross the network unencrypted |
| `--terminal admins\|master\|off` | Who may open a [terminal](#the-terminal): admins (the default), only the master, or no one (also `$DBS_MANAGER_TERMINAL`) |
| `--no-browser` | Do not open a browser; the address is printed either way |
| `--data-dir PATH` | Where the manager keeps everything (also `$DBS_MANAGER_HOME`) |
| `--database-url URL` | Use PostgreSQL or MySQL instead of SQLite (also `$DBS_MANAGER_DATABASE_URL`) |

The data folder holds the database, the backups it pulled and its log:

| System | Default data folder |
|---|---|
| Linux | `~/.local/share/django-dbs` (or `$XDG_DATA_HOME/django-dbs`) |
| macOS | `~/Library/Application Support/django-dbs` |
| Windows | `%LOCALAPPDATA%\django-dbs` |

`django_dbs paths` prints them, and where the sealing key is. Its SQLite database runs in
WAL mode with a 30-second busy timeout, and on Django 5.1 or later starts every write
transaction at once, so the interface, the scheduler and terminal commands share it without
"database is locked". The manager serves on 16 threads.

### The sealing key

Every server credential, backup passphrase, `.env` version and archive the manager holds is
sealed with AES-256-GCM under one key. The manager keeps that key in the system keychain
wherever one works, and reads it back before relying on it. Where no keychain works, the key
stays in `keys/secret.key` inside the data folder, and the manager warns at start, on the
dashboard and in its health report that anyone who can read the folder can open its secrets.

`DBS_MANAGER_KEY_STORE=keychain` or `=file` chooses the store yourself. The manager never
makes a new key when the keychain does not answer, and refuses to start when the keychain
and a key file disagree, naming both. On Windows a new data folder is limited to its owner.

### Accounts and roles

Every account has a role. Each role may do everything the one below it may:

| Role | What it may do |
|---|---|
| **viewer** | See the servers, applications, backups, plans, activity, `.env` key names and files; use the console for what a viewer may do |
| **operator** | Check servers and applications, take, verify and download backups, run plans, keep `.env` versions, download files, and rehearse restores, moves and deploys |
| **admin** | Add, change and remove servers and applications, read and store backup passphrases, upload and delete backups, change plans, reveal and push `.env` versions, change files, choose deploy steps, restore, move and deploy for real, and open a terminal |
| **master** | Everything, and the accounts: add them, set their roles, switch them off and on, reset their two-factor sign-in |

There is exactly one master, the account made at setup. It cannot be demoted or switched off;
it hands the role over instead, with its password and a current code. The interface hides
what a role may not do, and the manager refuses it whichever way it is asked.

Signing in to the interface takes the password and then a six-digit code from an
authenticator app, or one of the ten single-use recovery codes. An account without
two-factor sign-in sets it up at its next sign-in. A password lasts 30 days; after that, or
when the master asks for a new one, the session can only change it. Repeated failures slow
sign-in down for that username, from 2 seconds doubling up to a minute, except from an
address the account signed in from in the last 30 days.

The master manages accounts on the **Accounts** page, or from a terminal:

```bash
django_dbs createuser sara --role operator    # a first password; the account picks its own at first sign-in
django_dbs account list                       # role, active, two-factor, password expiry
django_dbs account role sara admin            # "master" hands the master role over
django_dbs account disable sara               # and enable
django_dbs account reset-2fa sara             # two-factor sign-in is set up again at the next sign-in
django_dbs password sara                      # a new password; its 30 days start again
```

`--password-stdin` scripts `createuser` and `password`.

### Listening beyond this computer

The manager listens on `127.0.0.1`. To reach it from elsewhere, put a TLS reverse proxy in
front of it and name the proxy's address range:

```bash
DBS_MANAGER_HOST=backups.example.com django_dbs run --host 0.0.0.0 --trusted-proxy 10.0.0.0/24
```

`X-Forwarded-Proto` and `X-Forwarded-For` are believed from that range only, cookies are
`Secure` and HSTS is on. `DBS_MANAGER_HOST` is the name you browse to. Without
`--trusted-proxy`, a non-loopback `--host` is refused unless you pass
`--allow-insecure-http`; an SSH tunnel to `127.0.0.1` needs neither.

The terminal reads its output with requests that wait up to 15 seconds for something to
show. Its answers carry `X-Accel-Buffering: no` and `Cache-Control: no-store`; nginx honours
the first unless `proxy_ignore_headers` lists it, so leave it out, and keep
`proxy_read_timeout` above 15 seconds (nginx's default of 60 is enough).

### Servers and applications

A **server** is a machine the manager reaches over SSH: its address and port, the SSH user,
how it signs in (a key the manager made, a key you gave it, or a password, each sealed), the
host key you confirmed, and the container engines it has. An **application** is one Django
project on a server, and where it runs:

| Where it runs | The manager runs `manage.py` … |
|---|---|
| **on the server** (`host`) | with the application's Python, in its project folder |
| **in a Compose service** (`compose`) | through `ENGINE compose [-f FILE]… [-p PROJECT] exec -T SERVICE …`, from the folder that holds the compose file |
| **in a container** (`container`) | through `ENGINE exec [-i] CONTAINER …` |

`ENGINE` is `docker` or `podman`. An application also keeps its paths inside the container
and on the server, its mounts, its backup folder, the folders its Files tab may open, its
`.env` and whether that file is on the server or inside the container, its backup passphrase
and its deploy steps. Backups, plans, `.env` versions, files, deploys and moves belong to an
application, so one server runs as many as it has. The dashboard shows each server with a
card per application.

Two servers that turn out to be one machine — the same address, port, user and host key —
can be joined: the interface offers it, or `django_dbs server merge OLD --into KEEP` moves
the applications across and removes the other, with your password. A server that still runs
an application cannot be removed (`server_has_applications`).

### Add a server

**Add a server** walks you through it:

1. **Address.** The server's name or address, its SSH port and user.
2. **Confirm the host key.** The manager shows the fingerprint the server presents and the
   command to run on the server to compare it. Nothing connects until you confirm it.
3. **Choose how to sign in.** Let the manager create a key — it shows the one line to add to
   the server's `~/.ssh/authorized_keys` — or paste a key or a password.
4. **Check.** The manager signs in and asks which container engines answer: Docker and
   Podman, their versions, their Compose, and whether this SSH user may use them.
5. **Add an application**, or come back to it later.

Each server shows a connection dot — online, offline with when it was last seen, or not seen
yet. The manager reaches every server it has not heard from in five minutes, sends a
keepalive every 15 seconds on an open connection, and notices a dropped one instead of
waiting on it. Where the server has the `timeout` command, every remote command runs under
it and is stopped at its deadline; until a command whose end was not seen has run out its
time, the manager starts no backup, restore or move on that application (`server_settling`).

### Add an application

You give the manager a server and a folder on it — the Django project's folder, or the
folder that holds the compose file that runs it. First the wizard asks **how the project
runs**, and every question may be answered *Not sure*:

| Question | Answers |
|---|---|
| Where does Django run? | on the server itself, in a Docker or Podman Compose service, in a single container |
| Which engine? | Docker or Podman |
| Which database, and where? | PostgreSQL, MySQL, MariaDB, SQLite or another; in the Compose project, on this server, on another machine or a managed service, or a file |
| Where do the settings come from? | a `.env` in the project folder, a Compose `env_file`, the image, the environment |
| Where does the code come from? | a git checkout, copied files, an image |
| What keeps it running, and what is in front of it? | systemd, a systemd user unit, Supervisor or other; nginx, another web server or none (for a project on the server itself) |

The answers guide the rest: the folder step says which folder to give, discovery puts the
place that matches them first, and a place that differs says so ("You said Podman, found
Docker"). Discovery and the check also read what they can without changing anything — the
database's vendor, host and name from the settings (never its password), the git branch,
commit, remote (without credentials) and uncommitted changes, where the `.env` comes from,
and the systemd units, Supervisor files and nginx sites that name the folder — and the
application's **How it runs** card on its overview shows each answer beside what was found,
with *Use what was found* and *Edit*. Changing the answers needs no password: they change no
command the manager runs. When the check finds a problem, it says what to do next for that
deployment, with the command to run (add the user to the `docker` group, mount the backup
folder into the service, install django-dbs in the image and rebuild it). From a terminal the
answers are `--deployment KEY=VALUE` on `app discover`, `app add` and `app edit`; `app show`
prints them beside what was found.

It finds the rest:

1. **The folder.** It lists the folder for `manage.py`, compose files, a `Dockerfile` or
   `Containerfile` and `.env` files. Left empty, it suggests the project folders it finds in
   the SSH user's home, `/srv`, `/var/www` and `/opt`, two levels down.
2. **Only a folder it can trust.** A folder that another account can write to, or whose
   parent another account can write to, runs nothing: discovery reports it and stops. The
   same holds for a project folder found below it.
3. **Containers.** For each engine the SSH user may use, it lists the containers and inspects
   them, and keeps those that belong to the folder: a Compose project whose working folder is
   in it, or a container with a bind mount from it. Replicas of one Compose service are one
   application, counted.
4. **Python and `manage.py`.** In each running container it tries the virtualenvs on the
   container's `PATH`, a `.venv` in its working folder, `/opt/venv`, `/venv`, `/app/.venv`,
   `/usr/local/bin/python3`, `python3` and `python`, keeps the first that has django-dbs, and
   looks for `manage.py` in the folder's mount, the container's working folder and `/app`,
   `/code`, `/srv`, `/usr/src/app` and `/opt/app`. On the server itself it tries any
   virtualenv in or next to the project, `~/.virtualenvs`, then `python3`, and keeps the one
   that has django-dbs.
5. **django-dbs itself.** It runs `manage.py dbs connection --json` where the project runs,
   for the settings module, the backup folder, the file roots, the `.env` path and the
   django-dbs version.
6. **Paths on the server.** A path inside a container is mapped to the server through the
   container's mounts, the longest matching one first, so the manager knows where the backup
   folder and the file roots are on the server. A backup folder that is on no mount is
   reported (`backup_dir_not_mounted`).
7. **`.env` candidates.** The `.env` django-dbs names, the `env_file` entries of the compose
   files, and the `.env` beside them, each marked as on the server or inside the container.
   Their contents are not read here.

Each place it found is offered with what it found, its problems (`container_not_running`,
`dbs_missing`, `dbs_too_old`, `backup_dir_not_mounted`) and the best one first. Pick one,
check the settings it filled in (*Show more settings* holds the rest), and the manager checks
the application: its engine answers and its container runs, django-dbs answers, the backup
command works, and the backup folder, the `.env` and the allowed folders are there.

**Store the passphrase**, read from the application so you never retype it. Do it now, before
the first backup: **an application's backup passphrase must never change**, because the
backups taken with it would no longer open. An application added without it gets a random
passphrase of the manager's own, which the backups the project writes by itself do not use.
Then **take a test backup**, and watch it arrive.

Adding an application asks for your password, because the manager will run its Python and
`manage.py` on the server; so does changing what it runs (where it runs, its engine,
container or Compose service, its folders, its Python, its `manage.py` and its settings
module) at any time. The Python must be named `python`, `python3`, `python3.N` or `pypy3`,
alone or as an absolute path, and `manage.py` must be a file called `manage.py`. For an hour
after adding a server, the account that added it searches the server without its password,
and changes the other settings of an application it added until its check passes; after
that, those ask for your password too.

### What a server needs before the manager can reach it

| On the server | |
|---|---|
| An SSH user that owns the project, with the manager's key in `~/.ssh/authorized_keys` | the manager needs no `root` and no shell profile; it uses `sudo` only to prepare the server a move goes to |
| The project, its Python and `manage.py`, on the server or in its image | the manager runs `manage.py dbs …` with fixed arguments |
| `pip install django-dbs` and `"dbs"` in `INSTALLED_APPS`, migrated | 0.7.0 or later; 0.8.0 or later to resume a transfer that broke |
| A stable `SECRET_KEY` (or `DBS_PASSPHRASE`) | the backup passphrase comes from it, and must never change |
| `DBS_BACKUP_DIR`, writable by the user the project runs as | where backups wait for the manager to collect them; in a container, on a mounted folder |
| For containers: a user that may run `docker` or rootless `podman` | see [Docker and Podman](#docker-and-podman) |

The project never contacts the manager and keeps nothing about it. A backup the manager
asks for is audited on the server like any other backup.

### Docker and Podman

For an application in a Compose service or a container, every command goes through the
engine as the SSH user:

```bash
docker compose -f compose.yaml -p shop exec -T -e DJANGO_SETTINGS_MODULE=shop.settings web python manage.py …
podman exec -i shop-web-1 python manage.py …            # -i only when the passphrase goes to stdin
```

* **Running or not.** A Compose service counts as running when the engine lists a running
  container with its project and service labels; a container, when the engine says so.
  `container_not_running` stops a backup before it starts.
* **Backups.** A backup streams out of the container; its copy waits in the container's
  `DBS_BACKUP_DIR`, where the next run collects it if the stream broke. Keep that folder on a
  mount, so the copy outlives the container.
* **Restores.** The backup goes into the container over standard input, into a private file
  under `/tmp` written as the container's own user, is restored there and removed. Nothing is
  staged on the server, and no `cp` or `chown` runs.
* **Leftovers.** Partial backups and restore files older than an hour are swept inside the
  container too.
* **`.env`.** A `.env` on the server is read over SFTP; one kept inside the container is read
  and replaced in place, and the interface warns that a version pushed there is lost when the
  container is recreated.
* **Read-only containers.** `dbs backup --stream` works in a container with a read-only root
  and a `tmpfs` at `/tmp`, as long as `DBS_BACKUP_DIR` is a writable mount.

**Who may use the engine.** The SSH user must be allowed to run the engine. For Docker that
means membership of the `docker` group, which amounts to root on that server, so give it to
the user that already deploys the project. With rootless Podman, run the containers as the
SSH user itself: its containers are its own, and its SSH login needs `XDG_RUNTIME_DIR` set,
as a systemd login does. `podman compose` uses the provider Podman is set up with, podman-compose
included. A bind-mounted folder must belong to the container's user inside Podman's user
namespace: `podman unshare chown 10001:10001 backups` gives it to user 10001 of the
container. Backups, restores and the check never use `sudo`. The check names what is wrong:

| Code | Means |
|---|---|
| `container_engine_missing` | Neither Docker nor Podman answers on this server |
| `engine_permission_denied` | The SSH user may not use the engine: add it to the engine's group, or run the containers with rootless Podman as that user |
| `container_not_running` | The application's container, or its Compose service, is not running |

### Off-site copies

The manager pulls; the server never pushes. Every DBS backup run, on demand or from a plan:

1. **collects** the backups waiting in the application's backup folder under its own or its
   plan's name — a stream that broke last time, or copies kept there — skipping any it
   already holds with the same path, size and SHA-256;
2. **streams a fresh backup** to itself with `dbs backup --stream`, showing the bytes as they
   arrive;
3. **verifies** each one: the size and SHA-256 the server reported, then a full decryption;
4. **removes the server's copies** it recorded and verified, keeping the newest `keep_remote`
   of them (0 to 5, none by default). Once a backup is verified with `keep_remote` at 0,
   nothing from the run stays on the server or in the container.

The manager keeps at most five good backups per application and plan, and never deletes the
newest one that passed verification. A file that fails verification is quarantined: kept
under a name that is not a backup name, with the reason, never restored and never counted.
The five newest quarantined files stay for you to inspect. A move refuses to restore a
quarantined backup (`backup_quarantined`).

**Transfers that break.** A server with django-dbs 0.8 names the backup it is writing and
reports its progress every 30 seconds. When the connection breaks mid-stream, the manager
keeps what it received, reconnects after 5, 15 and then 45 seconds, waits while the server
finishes the backup, pulls only the rest and checks the SHA-256 of the whole file before it
decrypts it to verify. A file that does not match is pulled again from the start, and
quarantined if that copy fails verification too. If it cannot reconnect, the run ends as *kept on the server*, not failed, and
the next run collects the backup. A stream stops only when nothing arrives for 15 minutes
(30 for a 0.7 server, which reports no progress), and a backup has a day in all. A 0.7
server's broken stream is collected on the next run.

**Storage.** **Backups** in the menu lists every application's backups in one place, beside
the space the backups kept in the manager take, in all and for each application. They are
in the data folder's `backups` folder; `django_dbs paths` prints where.

### Plans and their schedule

A plan takes a DBS backup, a folder archive or a file collection on a schedule — every hour,
3, 6 or 12 hours, every day or every week — or only when you run it, keeping 1 to 5 here and
0 to 5 on the server.

* **First run.** A plan starts at the moment you choose, and later runs keep its beat.
* **Time zone.** A daily or weekly plan keeps its local time in the time zone you name, such
  as `Europe/Berlin`, across daylight saving changes. UTC is the default.
* **Reschedule.** Move the next run to any moment within a year; later runs follow from it.
* **Pause and resume.** A paused plan does not run. Resumed, it runs at its next beat after
  now; the runs it missed are not made up.

The **Schedule** tab of an application does each of these, and so do
`POST /api/backups/plans/ID/reschedule/` (`{"next_run_at": "…"}`), `…/pause/` and
`…/resume/`, and the terminal:

```bash
django_dbs plan add shop nightly --kind dbs --every 1440 --first-run 2026-11-02T03:00+01:00 --time-zone Europe/Berlin --keep 5
django_dbs plan reschedule PLAN_ID --at 2026-11-03T04:30+01:00
django_dbs plan pause PLAN_ID
django_dbs plan resume PLAN_ID
```

A plan that keeps fewer backups than before deletes the oldest on its next run, so changing
it asks for your password. Two plans of one application cannot share a name that differs
only in case or punctuation.

### The same manager from a terminal

Everything the interface does is also a `django_dbs` command. Both call the same code and
the same data folder, so an application added in a terminal appears in the browser, a backup
the browser took is listed in the terminal, and the **Activity** page records both under
the account that acted.

```bash
django_dbs server add web-1 --host shop.example.com --user deploy --ssh-password
django_dbs server add web-2 --host 203.0.113.7 --user deploy --key-file ~/.ssh/web-2
django_dbs app discover web-1 --folder /srv/shop     # what is there, best first
django_dbs app add shop --server web-1 --folder /srv/shop
django_dbs app add blog --server web-2 --folder /srv/blog --candidate 2 --backup-passphrase
django_dbs app list
django_dbs backup take --all          # one after another, with a summary; exits 1 if one failed
django_dbs backup list --app shop
django_dbs plan add shop nightly --kind dbs --every 1440 --keep 5
django_dbs app remove blog
```

`server add` shows the host key fingerprint and asks you to confirm it (`--host-key` or
`--yes` from a script), signs in and checks the server. `--generate-key` prints the line to
add to `authorized_keys` instead. `app add` runs the discovery for the folder, adds the place
it found first (or the one `--candidate N` names from `app discover`), and checks it. Every
setting it found can be given instead: `--kind host|compose|container`,
`--engine docker|podman`, `--compose-project`, `--compose-service`, `--compose-file` (repeat
for more, in order), `--container`, `--project-dir`, `--workdir`, `--python`, `--manage`,
`--settings`, `--backup-dir`, `--env-path`, `--env-location host|container` and
`--file-root`. `app edit` takes the same.

| Area | Commands |
|---|---|
| `server` | `list` · `show` · `add` · `edit` · `remove` · `check SERVER… \| --all` · `merge SERVER --into SERVER` · `browse [PATH]` · `public-key` · `host-key` · `confirm-host-key ID` · `move SERVER --to SERVER [--real]` |
| `app` | `list [--server] [--search]` · `show` · `discover SERVER [--folder]` · `add --server --folder` · `edit` · `remove` · `check APP… \| --all` · `passphrase` · `capture-passphrase` · `deploy [--real]` · `deploy-steps [--set FILE]` |
| `backup` | `list [--app]` · `take APP… \| --all` · `verify` · `restore --mode merge\|replace [--to APP] [--real]` · `download [-o PATH]` · `upload` · `delete` · `undo-delete` |
| `plan` | `list` · `show` · `add` · `edit` · `remove` · `run` · `reschedule --at WHEN` · `pause` · `resume` |
| `activity` | `list [--server] [--app] [--action] [--status] [--limit]` · `show` |
| `env` | `list` · `pull` · `compare` · `reveal` · `push` |
| `files` | `list` · `download` · `upload` · `mkdir` · `delete` |
| `redeploy` | `start --from APP --to APP [--backup ID] [--env ID] [--flush] [--real]` · `revert JOB_ID [--real]` |

A server or an application is named by its name or its id; a backup, plan or `.env` version
by the id that `list` prints. Every command takes `--json`, which prints exactly what the web
API returns. `server list` and `server check` show each server's connection and engines, and
a long job prints a progress line every 30 seconds.

The terminal follows the interface's rules. Commands act as a manager account: the only one,
or the one named with `--as NAME`, within that account's role. An action the interface
protects with your password — changing a checked application's paths, revealing a passphrase
or a `.env`, a plan that keeps fewer backups, downloading what the manager keeps encrypted,
deleting a backup, removing a server or an application, choosing deploy steps, restoring,
moving or deploying for real — asks for it here too, or reads it with `--password-stdin`.
Secrets are typed at a prompt or read from stdin, never passed as arguments. Downloads are
saved readable by you alone. Removing a server or an application also asks you to type its
name unless you pass `--yes`. While the account's password has expired, every command says
so on standard error.

A command that takes a backup waits for it and prints the result. It can run while
`django_dbs run` is open: both take the same per-application lock, so a scheduled backup and
one from the terminal never run on one application at the same time. Starting the manager
frees the locks of jobs whose process is gone.

### The console

**Console** in the menu runs one `django_dbs` command line at a time, as the account you are
signed in with, in the browser: `app list`, `backup take shop`, `plan pause 3f2c…`. It takes
the `server`, `app`, `backup`, `plan`, `activity`, `env`, `files` and `redeploy` commands of
the terminal, `help` lists them, and a leading `django_dbs`, `django-dbs` or `dbs` is
ignored. A line is at most 2,000 characters and its
output at most 256 KiB, and an account runs one line at a time.

The console leaves out what reads this machine's disk or a secret from standard input:
`backup download` and `upload`, `files download` and `upload`, `server add` and `edit`,
`app passphrase`, `env reveal`, `app deploy-steps --set`, `mcp`, and the options `--as` and
`--password-stdin`. A command that needs your password asks for it in the console, and a job
it starts is shown as it runs; the console does not wait for it. Each line is recorded in
**Activity** with its verb and exit code, never its words. Every role may open the console,
and each command is still checked against the role.

`POST /api/console/` with `{"line": "…", "password": "…"}` does the same and answers
`{"exit_code", "output", "activities", "password_required"}`.

### The terminal

An admin can open a shell from the browser: on a server, as its SSH user, or for an
application — inside its container with `bash` (or `sh` where there is no `bash`), or in its
project folder on the server. The terminal tab of a server or an application opens one, with
your account password every time.

* At most four terminals are open at once, two per account.
* A terminal closes after 15 minutes without input, a minute without the browser asking for
  its output, or two hours in all, and when you sign out, your password or your role changes,
  or the manager stops.
* `django_dbs run --terminal master` (or `DBS_MANAGER_TERMINAL=master`) lets only the master
  open one; `--terminal off` switches terminals off.
* Its row in **Activity** records where it opened, its size, how long it ran, the bytes each
  way, how it ended and the exit status — never what was typed or shown.
* It runs as the SSH user, never through `sudo`. The console and the MCP server cannot open
  one.

The API is `/api/terminals/`: `POST` opens one (`mode` `server` or `application`, the id,
`password`, `cols` and `rows`), `GET /api/terminals/ID/output/?cursor=N` waits up to 15
seconds for output, `POST …/input/` sends keystrokes, at most 64 KiB at a time, `POST
…/resize/` changes its size, and `DELETE` closes it.

### Let Claude control the manager

`django_dbs mcp` is an MCP server, so Claude can fill the manager and look after the backups
for you. It runs on your machine, on the same data folder, and calls the same code as the
interface and the terminal, as one account and within that account's role.

```bash
claude mcp add dbs -- django_dbs mcp            # Claude Code
claude mcp add dbs -- django_dbs mcp --as sara  # when the manager has several accounts
```

For Claude Desktop, add it to `claude_desktop_config.json`:

```json
{ "mcpServers": { "dbs": { "command": "django_dbs", "args": ["mcp"] } } }
```

Use the full path to `django_dbs`, or `"command": "python", "args": ["-m", "dbs.manager",
"mcp"]`, if it is not on your `PATH`. Then ask, for example, *"add my server
shop.example.com, user deploy, find the application in /srv/shop and back it up"*.

What Claude can do:
- see the overview, servers, applications, backups, plans, activity, `.env` versions (key
  names only) and files;
- add a server, with an SSH password, a key file on this machine (the manager reads the file,
  Claude only names it), or a new key — once **you** have confirmed its host key. Claude reads
  the key and shows you the fingerprint; you confirm it on the **Servers** page or with
  `django_dbs server confirm-host-key ID` in a terminal. Claude cannot confirm it itself, and a
  key waits ten minutes for you;
- change a server's name or address, check servers and applications, discover and add an
  application from a folder, as discovery found it (Claude may choose the candidate and the
  backup folder, `.env` and allowed folders, never its Python, `manage.py`, folders,
  container or settings module), and store a new application's backup passphrase before its
  first backup;
- take, verify and save backups, add and run plans, keep more backups, and keep `.env`
  versions;
- rehearse a restore, a move, a deploy, a server move, or putting an application back after a
  move that stopped. A rehearsal changes nothing.

What Claude cannot do: reveal a passphrase or a `.env` value, restore, move a server or an
application, deploy or revert for real, give a `sudo` password, choose deploy steps, push a `.env`, make a plan keep fewer backups, save a file the manager keeps encrypted, remove a server or an application, delete backups or
files, open a console or a terminal, or pin or re-pin a host key you did not confirm. The MCP
server never takes your account password, so anything the interface protects with it —
changing a checked application's paths, archive and collect plans — comes back to you to do
in the interface or the terminal. Everything Claude does is in **Activity** under the account
it acts as.

An SSH password you give Claude passes through the conversation. Prefer a key file or a new
key when that matters to you.

### Backups, files and `.env`

Each application has tabs for **Backups** (take one now, upload one, verify, download,
restore), **Schedule** (its plans), **Files** (browse, upload, download inside the allowed
folders), **Environment** (every version of the `.env`, compared side by side, revealed only
after you type your password, and pushed back when you need it), **Deploy** (deploy in place,
or move to another application), **Terminal** and **Activity**. A server has **Overview**,
**Applications**, **Terminal** and **Activity**. The **Dashboard** shows every server with a
card per application: its connection, last backup, checks, next plan and recent failures;
**Activity** is the full audit trail, and a running job shows whether its connection is alive
and how much it has moved.

Downloading a folder archive, a collected or an uploaded file decrypts it, and so does
downloading a `.env` through the Files tab, so each asks for your password and the browser
follows a one-time link that lasts a minute. Deleting a backup or removing an application
asks for it too.

---

## Deploying and moving

### Deploying in place

An application keeps up to twelve **deploy steps**, chosen from a fixed list. Each step is
one fixed command whose names are checked, with its own time limit of 1 to 120 minutes (10
by default); no command line is ever taken from a request.

| Step | Options | Runs |
|---|---|---|
| `git_pull` | `remote` and `branch`, both or neither (letters, digits, `.`, `_`, `/`, `-`) | `git -C PROJECT pull --ff-only --no-rebase [REMOTE BRANCH]`, with `GIT_TERMINAL_PROMPT=0` |
| `compose_pull` | `services` | `ENGINE compose … pull [SERVICE…]` |
| `compose_build` | `services`, `pull` | `ENGINE compose … build [--pull] [SERVICE…]` |
| `compose_up` | `services` | `ENGINE compose … up -d [SERVICE…]` |
| `restart` | — | `ENGINE compose … restart SERVICE`, or `ENGINE restart CONTAINER` |
| `systemd_user_restart` | `unit` (a name ending in `.service`) | `systemctl --user restart UNIT` |
| `pip_install` | `requirements` (a file inside the project folder) | `PYTHON -m pip install -r FILE`, on the server itself |
| `migrate` | — | `manage.py migrate --noinput` |
| `collectstatic` | — | `manage.py collectstatic --noinput` |

`git_pull` and `pip_install` need the application's project folder; the `compose_` steps
need a Compose service, `restart` a container or a Compose service, and `pip_install` an
application on the server itself. Choose them on the **Deploy** tab, or from a JSON file:

```bash
echo '[{"kind": "git_pull"}, {"kind": "compose_build", "options": {"pull": true}}, {"kind": "compose_up"}, {"kind": "migrate", "timeout_minutes": 30}]' > steps.json
django_dbs app deploy-steps shop --set steps.json     # asks for your password
django_dbs app deploy shop                            # a rehearsal
django_dbs app deploy shop --real
```

A deploy for real needs your password and the application's name typed out. It:

1. checks the application, and records the image its container runs and, when a step pulls
   code, the git `HEAD`;
2. takes a **safety backup**, with no copy left on the server;
3. records the application's `.env` as a version;
4. runs the steps in order, stopping at the first that fails;
5. checks the application again, with `manage.py check` and `manage.py migrate --check`, and
   records the image and the git `HEAD` after.

The **rehearsal** only reads: `git fetch --dry-run` and `git status --porcelain`,
`compose config --quiet`, `pip --version` and a check that the requirements file is there,
`migrate --plan` and `collectstatic --dry-run`. It takes no backup and changes nothing.

When a deploy stops after a step that changed something, the deploy page offers **Restore
the safety backup**. It puts the data back as it was before the deploy began; the code and
the images stay as the deploy left them. Rehearse it first; for real it needs your password
and the application's name. From a terminal it is `django_dbs redeploy revert JOB_ID
[--real]`, with the deploy's activity number.

### Moving to another application

A move stands the project up as another application — on a new server, or another place on
the same one — that already runs its code with the same environment. The manager carries
the data and the `.env` across, and keeps a way back.

1. Prepare the new place: check out the project's code, with its virtualenv or its image,
   `django-dbs` among its requirements, with the same settings.
2. In the manager, **add the new application** with the wizard.
3. Open the old application's **Deploy** tab and choose **Move to another application**. Pick
   the new one, the `.env` version to push, whether to replace the new application's data
   instead of merging, and the backup to restore if the old application does not answer
   (its newest by default, or none to stop instead).
4. Run the **rehearsal**. It checks the new application, asks the old one whether it answers,
   and restores the backup in a transaction it rolls back. Nothing changes on either side. A
   rehearsal onto an application whose database is not migrated yet checks the backup in the
   manager instead — that it is whole and opens with the old application's passphrase.
5. Run it for real: type your password and the new application's name. The manager:
   1. checks the new application;
   2. backs up the old application now, when it answers, and keeps that backup with no copy
      left on the server; when it does not answer, it uses the backup you chose;
   3. records the new application's `.env` as a version;
   4. takes a safety backup of the new application's data, when its database is migrated;
   5. pushes the `.env`, runs `migrate`, restores the backup with the old application's
      passphrase, and checks the new application again.

The `.env` goes before the restore on purpose: it carries the old `SECRET_KEY`, which the
restored project needs for its sessions and its encrypted fields. Every step is in the audit
trail. A move never restores a quarantined backup.

When a step after the `.env` push fails, the move stops and names that step. The move page
then offers **Revert the new application**: it pushes the recorded `.env` back and restores
the safety backup, replacing what the move left there. Rehearse the revert first; a real
revert needs your password and the new application's name. From a terminal:

```bash
django_dbs redeploy start --from old --to new            # a rehearsal
django_dbs redeploy start --from old --to new --real
django_dbs redeploy revert 412 --real                    # 412: the move's activity number
```

### Moving a server

**Move to another server** on a server's overview carries every application on it onto
another server, with its code, `.git`, images, volumes, files, `.env` and data. The new server
may have nothing installed: the manager installs what the applications need. The old server
keeps running, untouched, until you point the traffic at the new one.

1. **Add the new server** — the move offers *Add a new server* and comes back to it — and
   choose it.
2. **Choose the applications** that move, the folder each takes (the same one by default) and
   its name. Application names are unique in the manager, so a moved application is called
   `NAME (NEW SERVER)` unless you name it.
3. **Plan the move.** The rehearsal only reads, on both servers, and lists what moves: each
   folder and its size, what is left out (the virtualenv when it is made again, a SQLite
   file), git, the images and volumes (the database's own volume stays: its data is restored
   instead), the database, the Python, the systemd units and nginx sites, and the packages the
   new server lacks. A blocker stops the move until you fix it — an unsupported system, a
   different processor for images, no `sudo`, too little space, a port, folder, file, image,
   volume, unit, site or container already on the new server, a name already taken, an
   application without a stored passphrase. Notes say what to check afterwards.
4. **Move for real** with your password, the new server's name typed out, and the `sudo`
   password of the SSH user on the new server when it needs one. The SSH user on the old server
   needs `sudo` only to read files it cannot read itself, and the move asks for that password
   only then.

The move then works in phases, each step in the audit trail:

- **Prepare the new server**: check the `sudo` password once, add Docker's own package
  repository (its signing key is checked against the fingerprint DBS ships) when Docker is
  needed, install the packages, start the engine and its services, add the users the units
  run as, and check the server again.
- **Each application**: take a fresh backup of it; carry its folder, files outside the folder
  such as a `.env` kept elsewhere, the folders mounted into its containers, its images
  (loaded and their ids compared) and its volumes; write the new folder into a carried `.env`
  that names the old one; make the backup folder; carry the virtualenv as it is, or make it
  again from `pip freeze` when the folder, the system or the Python differs; create the
  database for a PostgreSQL or MariaDB on the server itself; start the Compose services that
  ran (`compose up -d --no-build`, under the same project name) or the containers; add the
  moved application to the manager with the same backup passphrase and answers; run
  `migrate`, restore the fresh backup into it, install the systemd units and nginx sites with
  the new folder written into them (a site is enabled only when its certificates are there and
  `nginx -t` passes), check it, and copy its backup plans, paused.

Everything travels through the manager: read on the old server, written to a private spool
with its SHA-256, uploaded into a staging folder on the new server, checked there, then put
in place. Nothing on the new server is written over, and no `rm -r` runs: a folder lands
beside its place and is renamed into it only where nothing is. A database on another machine
or a managed service is shared by both servers, so the move does not restore over it. Rows
written on the old server after its fresh backup are not carried; move when it is quiet, or
take the old application offline first. A move that stops says which step and what it left
in the staging folder, and **Resume the move** starts again from there; only one move runs on
a server at a time, and a server a move holds cannot be removed.

The new server runs Debian 11, 12 or 13, Ubuntu 22.04, 24.04 or 26.04, RHEL, Rocky Linux,
AlmaLinux or Oracle Linux 8 to 10, CentOS Stream 9 or 10, or Fedora 41 or later, on amd64 or
arm64, with the same container engine as the old one. From a terminal:

```bash
django_dbs server move web-1 --to web-2                                # a rehearsal
django_dbs server move web-1 --to web-2 --app shop=/srv/shop --name shop=shop-eu
django_dbs server move web-1 --to web-2 --real                         # asks the passwords
django_dbs server move web-1 --to web-2 --real --resume 512            # 512: the move's activity number
```

`--skip-volume APP:VOLUME` leaves a volume behind, `--no-plans` copies no plan,
`--sudo-password-stdin` reads the `sudo` password after your own, and `--no-sudo-password`
says the SSH user is root or needs none. Claude can only rehearse a move
(`rehearse_server_move`); the console runs a real one only with `--no-sudo-password`.

### Moving the manager itself

The manager is just as portable:

```bash
django_dbs export manager.dbs                  # database and keys, one encrypted DBS file
django_dbs export manager.dbs --with-backups   # also every backup it pulled
django_dbs import manager.dbs                  # on the new machine, before the first run
```

`export` asks for a passphrase twice; keep it with the file. `import` builds the new
installation beside the data folder and then swaps it in, so a stopped import never leaves
half of one; the next start finishes the swap. It refuses to replace a manager that already
holds servers unless you pass `--replace`, and refuses while a manager is running on that
data folder. The installation it replaces is moved to `DATA-FOLDER.before-import-STAMP`,
never deleted. An export sealed with another key asks once more, or takes `--yes`. With
`DBS_MANAGER_DATABASE_URL`, `import` loads into an empty database instead. An export written
by 0.7 imports too: each of its servers becomes a server and an application.

---

## Restoring

```bash
python manage.py dbs restore backup.dbs --dry-run   # rehearse, change nothing
python manage.py dbs restore backup.dbs             # merge into what's there
python manage.py dbs restore backup.dbs --flush     # replace instead of merge
```

* **It merges by default.** Rows created after the backup was taken are kept, and an
  existing row only takes the fields the backup carries, so a field the backup leaves out
  keeps its value.
* **`--flush` replaces.** It deletes only the rows the backup covers — the rows a
  `ModelBackup.get_queryset` selects, on the database you restore into — children before
  parents, in the same transaction as the load.
* **The load is one transaction.** Rows load in the order the backup recorded, parents
  first. If anything fails midway the database is untouched.
* **Files land with the rows.** Every file's target is checked before any row loads. Files
  are written beside their targets and moved into place when the rows commit, and removed
  again if the load fails.
* **File writes are confined** to `DBS_RESTORE_ROOTS` (or `DBS_FILE_ROOTS` if unset), a
  `ModelBackup`'s own `file_roots`, and the storage of each file field, where a file lands
  under its storage name. Restoring onto a server whose paths differ? Map the old roots to the
  new ones with `DBS_RESTORE_PATH_MAP = {"/srv/old": "/srv/new"}`.
* **The dry run checks the same.** `--dry-run` names every file a restore would refuse, and
  exits non-zero when there is one.
* **Migration drift is reported**, naming the apps that moved on since the backup.
* **Sequences are raised**, so the next row your project creates does not collide; on
  PostgreSQL never below their current value. A dry run never touches them.
* **Rows the backup leaves out are found again by name.** `migrate` recreates content types
  and permissions on every server, numbered in the order that server migrated, so a backup
  refers to them, and to any other model it does not carry that has a natural key, by that
  key: a group's permissions as `["change_order", "store", "order"]`, a generic relation's
  content type as `["store", "order"]`. A permission the target no longer has is left out
  with a warning; a foreign key it cannot find stops the restore and names the row.

`--database` restores into another database alias, and `dbs backup --database` reads every
model, file and lookup from that alias.

Rows are saved the way `loaddata` saves them, with `raw=True`. A `post_save` receiver with
side effects should return early on raw saves:

```python
@receiver(post_save, sender=Order)
def on_order_saved(sender, instance, created, **kwargs):
    if kwargs.get("raw"):
        return
    ...
```

---

## Choosing what to back up

By default DBS finds every model, treats `FileField`/`ImageField` as files, and preserves
relations. Every row is backed up, including rows the default manager hides. Models with
`managed = False` are left out, since the project does not own their tables. A multi-table
child always brings its parent rows with it.

Register a model in a `dbs.py` inside your app to configure it. Once anything is registered,
only registered models are backed up:

```python
# myapp/dbs.py
from dbs import backup_registry, FieldType, ModelBackup
from .models import Invoice

@backup_registry.register(Invoice)
class InvoiceBackup(ModelBackup):
    overrides = {
        "scanned_pdf_path": FieldType.FILE_PATH,  # a path column -> embed the file
        "render_cache": FieldType.EXCLUDE,        # skip this column
    }
    file_roots = ["/srv/myapp/uploads"]           # extra file trees, also restore roots
```

`DBS_EXCLUDE_MODELS` skips models in addition to the built-in exclusions (content types,
permissions, admin log, sessions, and DBS's own records apart from the session guard's
policy and known locations). Prefix a label with `-` to back up one the defaults skip, an
unmanaged model included:
`DBS_EXCLUDE_MODELS = ["myapp.AuditRow", "-sessions.Session", "-legacy.Customer"]`.

Only regular files are read. A FIFO, socket or device, or a link that leaves its root, is
skipped and reported, so nothing in a file tree can hang a backup.

---

## Passphrases

DBS derives the backup passphrase from `SECRET_KEY`, domain separated so it is never the
same bytes Django uses for sessions and tokens. Order of precedence:

1. `--passphrase` or `--passphrase-stdin` on the command line
2. The `DBS_PASSPHRASE` environment variable
3. The `DBS_PASSPHRASE` setting
4. Derived from `SECRET_KEY`

> **Never change a project's backup passphrase.** Every backup is encrypted under the
> passphrase in force when it was written. Change `SECRET_KEY` without keeping the old one,
> set a new `DBS_PASSPHRASE`, or store a different passphrase for the application in the DBS
> manager, and every older backup stops opening. Nobody can open a backup whose passphrase
> is lost.

**Rotating `SECRET_KEY`:** keep the old value in `SECRET_KEY_FALLBACKS`. DBS tries every
fallback when restoring, so a rotation done the supported Django way does not strand old
backups. Archive `python manage.py dbs key --show` before you rotate.

The DBS manager stores each application's backup passphrase, sealed, and hands it to the
project on standard input for every backup and restore. Store it once, while you add the
application and before its first backup — *Backup passphrase* in the wizard, or
`django_dbs app capture-passphrase APP` — and never replace it afterwards.

---

## The session guard

The panel can export and overwrite your whole database, so every admin request from a
superuser is scored — time of day, request rate, how risky the action is, session age,
failed logins, and whether the network and browser are familiar — by an `IsolationForest`
shipped pre-trained and refitted in the background on the account's own history. Changes to
users, groups, permissions and passwords count as high-risk actions.

* **A warning flags the session.** A flagged session can still read, but every change
  anywhere in the admin, and every download or export, is refused and ends the session; it
  must sign in again.
* **A high enough score ends that account's sessions.**
* **Learning never switches enforcement off.** During an account's first sessions the model
  is muted, because everything about a new account looks unusual, but the rules and both
  thresholds still apply.
* **Idle sessions end.** A session idle in the admin for longer than the policy's idle
  timeout (from 15 minutes to 8 hours by level; 0 turns it off) is ended on its next request.
* **Telemetry is kept short and coarse.** Session events store the /24 (IPv4) or /48
  (IPv6) network and a keyed hash of the full address, anomalies only the network.
  Telemetry older than `DBS_SECURITY_RETENTION_DAYS` (90 by default) is removed once a day.
  The audit trail is never purged with it.

**If it locks you out, a shell always wins:** `python manage.py dbs security unlock alice`.

Loosen it with `DBS_TRUSTED_NETWORKS`, `DBS_ANOMALY_ENFORCE = False`, or a more relaxed level
in the setup wizard. `DBS_GEOLOCATION = True` adds browser location, which can only ever
raise a score.

Behind a reverse proxy, set `DBS_TRUST_FORWARDED_FOR = True` and list the proxies' networks
in `DBS_TRUSTED_PROXIES`, for example `["10.0.0.0/24"]`. `X-Forwarded-For` is read only from
a request that arrives from one of them, walking the header from the right to the first
address that is not a proxy. An address the guard cannot read counts as a new network.

The forest needs scikit-learn, which `pip install django-dbs` installs. If it cannot be
imported, the guard scores with its rules alone. `manage.py check` warns about the three ways
a guard can be set up wrong:

| Check | Means |
|---|---|
| `dbs.security.W001` | `DBS_TRUST_FORWARDED_FOR` is on but `DBS_TRUSTED_PROXIES` names no proxy network |
| `dbs.security.W002` | `DBSSecurityMiddleware` runs before `AuthenticationMiddleware`, so it scores nothing |
| `dbs.security.W003` | scikit-learn cannot be imported; `pip install --force-reinstall "django-dbs"` repairs it |

---

## Working with AI assistants

```bash
python manage.py dbs ai            # writes .claude/skills/django-dbs/
python manage.py dbs ai --agents   # also appends a section to AGENTS.md
python manage.py dbs ai --check    # CI: fail if the installed copy has drifted
```

The instructions live inside the installed package under `dbs/ai/`, so they always match
the version you have.

To let Claude operate the manager itself — add servers and applications, take and verify
backups, set up plans — connect its MCP server:

```bash
claude mcp add dbs -- django_dbs mcp
```

[Let Claude control the manager](#let-claude-control-the-manager) lists what Claude can and
cannot do.

---

## Command reference

```bash
python manage.py dbs                    # overview
python manage.py dbs backup OUTPUT      [--database] [--allow-missing-files] [--no-compress] [--no-verify]
python manage.py dbs backup --stream    [--prefix P] [--output-dir DIR] [--progress-seconds N] [--passphrase-stdin]
python manage.py dbs restore INPUT      [--dry-run] [--flush] [--no-data] [--no-files] [--database]
python manage.py dbs validate INPUT     [--passphrase | --passphrase-stdin]
python manage.py dbs schedule           [--once] [--interval 6h --output-dir DIR --keep 1-5]
python manage.py dbs health             [--json]
python manage.py dbs audit verify
python manage.py dbs connection         [--json]
python manage.py dbs key                [--show]
python manage.py dbs security ACTION    [USERNAME]
python manage.py dbs ai                 [--agents] [--check] [--print]
python manage.py dbs upgrade            [--check] [--self [--to X.Y.Z] [--yes] [--system-python]] [--backups DIR] [--offline]

django_dbs run                          [--port] [--host] [--trusted-proxy CIDR] [--allow-insecure-http] [--terminal admins|master|off] [--no-browser]
django_dbs export [FILE]                [--with-backups] [--passphrase-stdin]
django_dbs import FILE                  [--replace] [--yes] [--passphrase-stdin]
django_dbs createuser NAME              [--role admin|operator|viewer] [--password-stdin]
django_dbs password NAME                [--password-stdin]
django_dbs account  list|role|disable|enable|reset-2fa
django_dbs paths · --version

django_dbs server   list|show|add|edit|remove|check|merge|browse|public-key|host-key|confirm-host-key
django_dbs app      list|show|discover|add|edit|remove|check|passphrase|capture-passphrase|deploy|deploy-steps
django_dbs backup   list|take|verify|restore|download|upload|delete|undo-delete
django_dbs plan     list|show|add|edit|remove|run|reschedule|pause|resume
django_dbs activity list|show  ·  django_dbs env list|pull|compare|reveal|push
django_dbs files    list|download|upload|mkdir|delete  ·  django_dbs redeploy start|revert
                                        [--as NAME] [--json] [--password-stdin]
django_dbs mcp                          [--as NAME]
```

`django-dbs` and `dbs` are the same command as `django_dbs`. Every one takes `--data-dir`,
and every one but `paths` takes `--database-url`. `django_dbs AREA VERB --help` lists each
command's options, and `python -m dbs.manager COMMAND` is the same as `django_dbs COMMAND`.

`dbs security` takes `status`, `unlock USER`, `policy`, `retrain`, `reset-baseline USER`,
`events` and `purge`; `status` shows the idle timeout and the state of the anomaly model.

`dbs schedule` with no plan flags follows the panel's schedule; with `--interval`,
`--output-dir`, `--prefix` or `--keep` it runs that plan instead. `python manage.py
django_dbs` and `python manage.py django-dbs` are the same umbrella as `manage.py dbs`, and
`dbs_backup`, `dbs_restore`, `dbs_validate` and `dbs_schedule` still work.

`dbs connection --json` prints what the manager reads from a project, with `"container":
true` when it runs in one; it then leaves out the hostname, SSH user and host keys, which
describe the container, not the server.

---

## Settings reference

Everything is optional. DBS works with none of these set.

| Setting | Purpose |
|---|---|
| `DBS_BACKUP_DIR` | Where backups are kept, at most five, restored from and checked |
| `DBS_SCHEDULER` | `"thread"` (default), `"command"` or `"off"` |
| `DBS_SCHEDULE_INTERVAL` · `DBS_SCHEDULE_KEEP` | Seed the panel's first schedule, and the defaults for `dbs schedule` with flags. `DBS_SCHEDULE_KEEP` is 1 to 5 (default 5) |
| `DBS_BACKUP_PREFIX` | Filename prefix, so several projects can share a directory |
| `DBS_EXCLUDE_MODELS` | Models to skip, in addition to the defaults. `-label` re-includes one |
| `DBS_FILE_ROOTS` · `DBS_RESTORE_ROOTS` | Extra directories to embed; directories a restore may write into |
| `DBS_RESTORE_PATH_MAP` | `{"/old/root": "/new/root"}`: where a restore puts files from a server whose paths differ |
| `DBS_PASSPHRASE` | An explicit passphrase, overriding the derived one. Never change it once there are backups |
| `DBS_KDF_TIME_COST` · `DBS_KDF_MEMORY_COST` · `DBS_KDF_PARALLELISM` | Argon2id cost for new backups. A backup refuses a time cost above 10 or a memory cost above 262144 KiB |
| `DBS_JOB_PROCESS` | `False` runs panel jobs in a thread of the web process instead of their own process. Default `True` |
| `DBS_JOB_TIME_LIMIT` · `DBS_JOB_MEMORY_LIMIT` | When a panel job is stopped: `"6h"` and `"2G"` by default; a memory limit of `0` means none |
| `DBS_JOB_NICE` | How much a panel job lowers its priority (default 10) |
| `DBS_JOB_PYTHON` · `DBS_JOB_BOOTSTRAP` | The interpreter that runs panel jobs, when it is not the project's; a dotted path to the callable that sets Django up in it, instead of `django.setup` |
| `DBS_SETUP_WIZARD` | Send superusers to the guard wizard until it is configured. Default `True` |
| `DBS_ANOMALY_ENFORCE` · `DBS_TRUSTED_NETWORKS` · `DBS_GEOLOCATION` | Guard enforcement, trusted CIDRs, browser location |
| `DBS_ANOMALY_DETECTOR` · `DBS_ANOMALY_MIN_ROWS` | A replacement detector class; events before a per-account model is fitted |
| `DBS_GUARD_POLL_SECONDS` · `DBS_GUARD_EVERYWHERE` | How often an open page re-checks; whether the poller covers the whole admin |
| `DBS_SECURITY_RETENTION_DAYS` | How long guard telemetry is kept before it is purged (default 90) |
| `DBS_MAX_UPLOAD_BYTES` · `DBS_MAX_PAYLOAD_BYTES` | Restore upload cap (1 GiB); decompressed payload cap for format 1 backups (4 GiB) |
| `DBS_TRUST_FORWARDED_FOR` · `DBS_TRUSTED_PROXIES` | Read the client address from `X-Forwarded-For`, only from the listed proxy networks |

The manager reads its own environment variables:

| Variable | Purpose |
|---|---|
| `DBS_MANAGER_HOME` | The data folder |
| `DBS_MANAGER_DATABASE_URL` | `postgres://…` or `mysql://…` instead of the local SQLite file |
| `DBS_MANAGER_KEY_STORE` | `keychain` or `file`: where the sealing key lives |
| `DBS_MANAGER_HOST` | The name you browse to, behind a proxy |
| `DBS_MANAGER_TRUSTED_PROXY` | The proxy ranges, as `--trusted-proxy` sets them |
| `DBS_MANAGER_TERMINAL` | `admins` (default), `master` or `off`: who may open a terminal, as `--terminal` sets it |

---

## Python API

```python
from dbs import write_backup, restore_backup, validate_backup

summary = write_backup("backup.dbs", "passphrase")   # streams; returns a BackupSummary
print(summary.bytes_written, summary.sha256, summary.records, summary.skipped_files)

report = validate_backup("backup.dbs", "passphrase")  # report.ok, report.summary()
result = restore_backup("backup.dbs", "passphrase")   # result.healed if it repaired corruption
```

`write_backup` streams to a path that does not exist yet, or to any binary file object — an
open file, `sys.stdout.buffer`, a socket's file — with memory that stays flat. It takes
`using`, `models`, `registry`, `compress`, `verify`, `allow_missing_files`,
`skipped_files` and `workers` (threads for parity and encryption, 1 by default).
`create_backup(passphrase, ...)` returns the backup as bytes, for small projects.
`restore_backup` and `validate_backup` take bytes, a path or a seekable binary file.
`restore_backup(..., dry_run=True)` lists refused files in `result.files_refused`.

```python
from dbs.transports import SSHTarget, open_session

target = SSHTarget(
    host="backups.example.com",
    username="deploy",
    key_filename="~/.ssh/id_ed25519",
    host_key="ssh-ed25519 AAAA…",
    remote_dir="/var/backups/myproject",
)
with open_session(target) as session:
    for item in session.details():
        print(item.name, item.size, item.modified)
```

`dbs.transports` comes with `pip install django-dbs`; paramiko is imported only when you use
it. Host keys are verified and unknown hosts are rejected by default: pin the one key you
expect with `host_key`, or point `known_hosts` at a file. `fetch_host_key(host)` reads a key
so you can compare its `fingerprint` with the one the server prints
(`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`) before you store its `line`. A server
that presents a different key raises `HostKeyError`. A session sends a keepalive every 15
seconds, notices a dropped connection, and stops a remote command after `command_timeout`
(6 hours by default). `SSHSession.stream()` takes an `idle_timeout`, after which a command
with no output on either stream is stopped, and an `on_stderr_line` callback that sees each
line of standard error as it arrives. `SSHTarget.from_dict` reads `username` and
`key_filename`; the older `user` and `key_file` keys are refused.

---

## How it heals

On write, the payload is compressed in 1 MiB segments and encrypted in chunks with
AES-256-GCM, one chunk per block. Each chunk is authenticated together with the file's
header, under a nonce that carries its position, so a block moved, swapped, dropped or taken
from another backup fails authentication. Each block gets Reed-Solomon parity and a keyed
BLAKE2b tag, and is stored **twice**: the second copy is written 64 blocks after the first,
so a burst of damage up to about 4 MiB never reaches both copies of a block. The header,
which carries the layout, the Argon2id parameters, the salt and the wrapped data key, is
written at the start and the end with a checksum, and two checksummed trailers carry the
block count and a digest over every block tag. No plain hash of your data is stored.

On read, each block is taken from whichever copy verifies, and sparse bit-flips are
corrected in place even when *both* copies are hit. A block that neither copy yields on its
own is rebuilt from both, one 255-byte codeword at a time: each codeword comes from whichever
copy decodes, and where the two copies disagree those bytes are treated as erasures, of which
Reed-Solomon corrects twice as many. Only a header copy that verifies is used, so damage to
one never hides a backup, and a file cut short still yields its block count from the blocks
themselves. A freshly written backup is re-read and verified end to end, both copies
included, before the command reports success.

**Recoverable:** whole-block loss in one copy; sparse byte errors in both copies up to the
parity budget (about 8 bytes per codeword by default); damage in both copies of the same
block, as long as each codeword survives in one copy or the copies differ in at most 16 of
its bytes; and damage to one copy of the header or the trailer. **Not recoverable:** a
codeword destroyed beyond that in both copies — DBS then refuses to restore and names the
failed blocks.

This is container format 2. Backups written in format 1 by earlier releases still validate
and restore, read whole within `DBS_MAX_PAYLOAD_BYTES`. `dbs upgrade --backups DIR` converts
them: each one is written to a new `NAME.v2.dbs` beside it, readable by its owner alone, and
validated end to end before it takes that name. The original is never touched.

## Security model

* **Argon2id** derives a key from the passphrase; **AES-256-GCM** encrypts the payload under
  a random data key wrapped by it. The file never holds the passphrase or the raw data key.
  A format 2 backup that asks for an Argon2id time cost above 10 or more than 256 MiB of
  memory is refused before any work, so a crafted file cannot tie up the machine that reads
  it.
* A wrong passphrase fails authentication before any data is produced; it never yields
  partial or garbage data.
* Every local backup file, and every temporary file it is written through, is readable by its
  owner alone from the first byte. An SFTP upload is too, before its bytes arrive.
* A panel job's passphrase reaches its child process on standard input, never in its
  arguments or its environment.
* Every server credential, passphrase, `.env` version and archive in the manager is sealed
  with AES-256-GCM under its sealing key, kept in the system keychain where one works, and
  never returned by any page or API.
* SSH host keys are verified by default; the manager pins exactly the key a person
  confirmed. Remote commands are built from fixed argument lists, and passphrases travel on
  standard input, never on a command line. Deploy steps come from a fixed list; no command
  line is taken from a request.
* Discovery runs nothing in a folder, or a project below it, that another account can write
  to, and reads nothing from a container's environment but `DJANGO_SETTINGS_MODULE` and the
  virtualenv folders on its `PATH`.
* The terminal is for admins, asks the account password for every shell, closes on sign-out
  or a password or role change, and records no keystroke or output. The console and the MCP
  server never reach it.

See [SECURITY.md](SECURITY.md) for the reporting process and the threat model.

## Observability

DBS logs to the `dbs` logger, including a `WARNING` whenever silent corruption was detected
and healed. Route it somewhere you will see it. The manager also writes `manager.log` in its
data folder.

---

## Troubleshooting

**Scheduled backups never run.** Open *Health*. "The scheduler has not checked in" means no
worker has served a request since it started, or the server runs uWSGI without
`--enable-threads`; use `DBS_SCHEDULER = "command"` and `manage.py dbs schedule`.

**"Set DBS_BACKUP_DIR"** — the schedule, *Take a backup*, restore from a stored backup,
`dbs backup --stream` and health need it.

**"Cannot keep backups in …"** — the user DBS runs as cannot create or write that folder.
Point `DBS_BACKUP_DIR` at one it can. In a container that runs as a non-root user, create
the folder in the image and give it to that user, or a new volume mounted there is owned
by root.

**A panel backup fails with `disk_full`, `permission_denied` or `read_only`.** The backup
folder is full, not writable by the user the project runs as, or on a read-only disk. Older
backups are untouched; free space or fix the folder, and the next backup succeeds.
`database_failed` means the database connection broke while the backup read it.

**A panel job fails with `time_limit`, `memory_limit` or `killed`.** It ran longer than
`DBS_JOB_TIME_LIMIT`, used more than `DBS_JOB_MEMORY_LIMIT`, or its process ended some other
way, as when the server ran out of memory. Raise the limit, or look at the server's own log
for the process.

**Panel backups fail to start: the process cannot load the project.** The interpreter DBS
chose for panel jobs is not the project's. `manage.py dbs upgrade` names it; set
`DBS_JOB_PYTHON` to the virtualenv's Python, `DBS_JOB_BOOTSTRAP` if the project sets Django
up its own way, or `DBS_JOB_PROCESS = False`.

**`dbs backup` says the file already exists.** It never replaces a backup. Choose a new name
each run, or let the schedule name them.

**A backup stops naming files it cannot read.** Restore the files, or pass
`--allow-missing-files` to back up without them.

**The panel logged me out.** `python manage.py dbs security unlock USERNAME`, then add your
network to the trusted list.

**`/admin/dbs/` gives a 404.** The panel is for superusers only, and needs
`django.contrib.admin` in `INSTALLED_APPS` alongside `dbs`.

**A restore raises `RestoreError` about a path.** Add the directory to `DBS_RESTORE_ROOTS`, or
map the old root to a new one with `DBS_RESTORE_PATH_MAP`. `--dry-run` lists every file a
restore would refuse.

**The project will not start after the upgrade: `dbs.contrib` is gone.** Delete
`include("dbs.contrib.urls")` from your URLconf; take and restore backups at `/admin/dbs/` or
from the DBS manager. `manage.py dbs upgrade` names the file.

**`django_dbs` says the installation cannot import a package.** Repair it with
`pip install --force-reinstall "django-dbs"`.

**`django_dbs run` shows "The manager's interface is not built".** You installed from a
source checkout. Install from PyPI, or build it once with `scripts/build_manager_ui.sh`.

**`django_dbs` is not recognized / command not found.** pip installed the script into a
folder that is not on your `PATH`, common with Windows user installs and
`pip install --user`; pip prints that folder in a warning during the install. Add it to
`PATH`, or run `python -m dbs.manager run` instead.

**`django_dbs run` will not start: the system keychain refused.** Unlock the keychain and
start again, or set `DBS_MANAGER_KEY_STORE=file` to keep the sealing key in the data folder.

**The manager cannot reach a server.** Check it again on its page, or
`django_dbs server check SERVER`: it names whether the SSH login or the host key is the
problem, and which container engines answer. `django_dbs app check APP` names whether the
project path, the Python, the container or the application's django-dbs version is. An
application whose django-dbs is older than 0.7 answers `dbs_too_old`; upgrade it.

**The check says `engine_permission_denied`.** The SSH user may not use Docker or Podman. Add
it to the `docker` group, or run the application's containers with rootless Podman as that
user. The check never uses `sudo`. `container_engine_missing` means neither engine answers;
`container_not_running` that the application's container is stopped.

**Discovery found nothing, or ran nothing in the folder.** A folder that another account can
write to, or whose parent another account can write to, is reported and left alone; let only
its owner write there and search again. A container belongs to a folder only through its
Compose working folder or a bind mount from the folder.

**A terminal command says "pick the account to act as".** The manager has more than one
account; add `--as NAME`.

**A command or a page says it needs another role.** Your account's role does not allow it.
Ask the master account for a higher one.

**A terminal command says it asks for a secret to be typed.** It ran without a terminal, as
from cron. Pass the password on stdin with `--password-stdin` (or the SSH password with
`--ssh-password-stdin`), and `--yes` for confirmations.

**The terminal tab is missing or refuses to open.** It is for admins, and needs your password
every time; `django_dbs run --terminal master` limits it to the master and `--terminal off`
switches it off. `too_many_terminals` means four are open, or two of yours.

**The manager says django-dbs is "Not found" on a server that has it.** The manager runs the
Python saved for that application over a non-interactive SSH login, which loads no
virtualenv. The check names the Python it used and the error it got, and offers the Python
where django-dbs is installed; choose *Use this Python*. Or search the folder again from the
application's settings.

**Backups taken by the manager fail verification.** They are quarantined, never restored.
The usual cause is a backup passphrase in the manager that is not the application's: the
passphrase must be the one its backups were taken with.

---

## Upgrading

Pin the release in your requirements or lock file and reinstall:

```bash
pip install "django-dbs==X.Y.Z"
python manage.py dbs upgrade
```

It applies pending DBS migrations itself, and prints, with the exact line to add, anything
that means editing your own code. `--check` changes nothing and exits non-zero when an item
needs you to act, for CI; warnings are printed and leave it passing. Inside a virtual
environment, `dbs upgrade --self` installs the newest release (or `--to X.Y.Z`): it prints
the pinned `pip install` command and asks first (`--yes` answers for a script), names the
requirement files to pin it in too, leaves a source checkout alone, and an interpreter
outside a virtual environment unless you add `--system-python`.

`--backups DIR` reads old backups and converts any written in an older format into a new
file beside the original. Nothing in DBS ever deletes or overwrites a backup.

### From 0.7.x

```bash
pip install --upgrade django-dbs
python manage.py dbs upgrade
```

Backups keep container format 2 and no DBS migration was added for projects, so a 0.7
project reads 0.8 backups and the other way round. `dbs upgrade` reports these:

| Step | What it says, and what to do |
|---|---|
| dependencies | `pip install django-dbs` now installs scikit-learn, paramiko, djangorestframework, waitress and keyring. One that cannot be imported is named, with `pip install --force-reinstall "django-dbs"` |
| install extras | A requirement file still names `django-dbs[guard]`, `[manager]`, `[ssh]` or `[all]`; write `django-dbs` without the brackets. The names add nothing in 0.8 and go away after it |
| contrib views | `dbs.contrib`, the original in-request backup and restore views, is gone. A URLconf or `INSTALLED_APPS` that still names it would stop the project starting; delete `include("dbs.contrib.urls")` |
| command names | A `Makefile`, `Procfile`, `Dockerfile`, compose file, shell script or workflow still runs `dbs-upgrade`; use `python manage.py dbs upgrade` |
| old partial files | `.part` files left in `DBS_BACKUP_DIR` by a backup before 0.7 are no backups, and DBS no longer sweeps them; the `rm` line removes them |
| panel jobs | Panel backups, restores and scheduled runs now run in a process of their own. The step starts the interpreter DBS will use and checks it loads the project; if not, set `DBS_JOB_PYTHON`, or `DBS_JOB_PROCESS = False` |
| mysql reads | On MySQL, backups read one consistent snapshot; a `max_allowed_packet` below 64 MiB is reported, since a larger value would not restore |
| sqlite writes | On SQLite, a journal mode other than WAL, or deferred transactions on Django 5.1 or later, can make the site's writes fail with "database is locked" while a backup reads; the step prints the `OPTIONS` to set |
| ssh target keys | `SSHTarget.from_dict` reads `username` and `key_filename`; rename `user` and `key_file` |

A project that pins `djangorestframework` below 3.15 now meets a resolver conflict, since
django-dbs needs 3.15 or later; raise the pin. Every bundled package is capped below its next
major version.

**The manager** migrates itself the next time any `django_dbs` command starts. Each 0.7
server becomes a server (its address, credentials and host key) and an application (its
project, paths, passphrase and plans) with the old server's id, so its backups, plans, `.env`
versions and audit rows stay where they were; join servers that are one machine with
`django_dbs server merge`. On SQLite it first keeps a copy of the database as
`manager.sqlite3.pre-0.8.0` beside it and names it at start; on PostgreSQL or MySQL it
writes a warning to `manager.log`, so back that database up before you upgrade. The servers
it backs up need django-dbs 0.7.0 or later, and 0.8.0 to resume a transfer that broke. The
wizard no longer reads a pasted `dbs connection --json`: give it the SSH address and the
folder.

**Going back to 0.7.** For a project, `pip install "django-dbs[guard]==0.7.0"`, since 0.7
installs the guard's detector only with its extra; 0.8 added no project migration and kept
the backup format, so nothing else changes back. For the manager: stop it,
`pip install "django-dbs[manager]==0.7.0"`, move `manager.sqlite3.pre-0.8.0` back over
`manager.sqlite3` in the data folder (`django_dbs paths` prints it), and start it. Backups the
manager took after the upgrade stay in its backups folder, but the old database does not list
them.

### From 0.6.x

Run `dbs upgrade` as above. It applies the migration that seals the audit
trail and drops the SFTP targets, and reports each of these along with the 0.8 steps:

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
two-factor sign-in at its next web sign-in; plans keep 1 to 5 backups here and 0 to 5 on the
server; and every server needs django-dbs 0.7 or later to be backed up. `django_dbs redeploy
start` no longer takes `--archive` or `--migrate`.

### From 0.5.x and 0.4.x

**From 0.5.x:** `dbs schedule` with no flags now follows the panel unless
`DBS_SCHEDULE_INTERVAL` is still set. If its schedule is off, the command waits for it
instead of backing up every 24 hours; turn the schedule on, or pass `--interval`.
`dbs upgrade` says so when it applies. The manager applies its own new migrations the next
time any `django_dbs` command starts.

**From 0.4.x:** `dbs upgrade` applies the audit and schedule migrations. If you set
`DBS_SCHEDULE_INTERVAL`, turn the schedule on once in the panel, or keep running
`dbs schedule --interval …` as before. Projects behind uWSGI without threads should set
`DBS_SCHEDULER = "command"`.

## Development

```bash
pip install -e ".[dev]"
scripts/test.sh                       # every suite below, each with its own settings
DBS_TEST_HOUR=3 pytest                # the guard scores time of day; pin it
scripts/build_manager_ui.sh           # build the manager's interface into the package (needs Node)
```

`scripts/test.sh` runs the library suite, then each of these as its own session:

| Suite | Settings | What it covers |
|---|---|---|
| `tests/manager` | `tests.manager.settings` | The manager |
| `tests/isolation` | `tests.isolation.settings` | Panel jobs in real child processes, failing backups, several instances of one project on one database |
| `tests/scaling` | `tests.scaling.settings` | Two hundred applications on one manager with plans due the same minute |
| `tests/load` | `tests.load.settings` | A backup while a Django site is under load |
| `tests/scale` | `tests.scale.settings` | A thousand tables and a large table (`DBS_SCALE_TABLES`, 1,000; `DBS_SCALE_ROWS`, 1,000,000; `DBS_SCALE_MEMORY_MB`, 1024) |

`scripts/test.sh` runs the load and scale suites short (`DBS_LOAD_BASELINE=5`,
`DBS_LOAD_AFTER=3`, `DBS_SCALE_ROWS=20000`). Other switches:

* `DBS_TEST_DB=postgres|mysql` runs the library suite on another database, and
  `DBS_MANAGER_DATABASE_URL` the manager suite.
* `DBS_LARGE_VALUE_MB` sets the size of the large-row tests (8 by default; 100 in CI), and
  `DBS_SLOW_TESTS=1` runs the slowest stream tests.
* `DBS_TEST_FULL_DISK=/mnt/tiny` points one isolation test at a small tmpfs, such as one of
  1 MiB, for a backup that fills a real disk.
* `python scripts/load_backup.py --report-dir .` serves a small Django app under steady load,
  takes a panel backup and a streamed backup while it runs, and writes `load-report.md` and
  `load-report.json`: requests per second, latency percentiles, errors and memory before,
  during and after. `--p95-factor` (or `DBS_LOAD_P95_FACTOR`, 2) is how much slower the 95th
  percentile may get.
* `python scripts/upgrade_rehearsal.py` installs django-dbs 0.7.0 from PyPI in a new
  virtualenv, fills a project and a manager, upgrades both to this checkout and checks that
  nothing was lost; `--from-version` and `--keep` change what it starts from and whether its
  folder stays.

The SSH and container tests run against real servers when they are named:

```bash
sudo scripts/openssh_test_server.sh /tmp/dbs-sshd 2222 > ssh.env           # DBS_TEST_SSH_*
sudo scripts/container_fixture.sh docker /srv/dbs-live > containers.env     # or podman
set -a; . ./ssh.env; . ./containers.env; set +a
python -m pytest tests/test_ssh_openssh.py
python -m pytest tests/manager/live --ds=tests.manager.settings
```

`container_fixture.sh` builds a small Django project into an image with this checkout's
wheel and starts it with Compose as the SSH test account, rootless under Podman; the live
tests add the server and the application by its folder, back it up, restore it, deploy it,
open a terminal in its container, and stream a backup from a read-only container.

The manager's interface lives in `manager-ui/` (Angular, Angular Material). For live
reload, run `django_dbs run --no-browser --port 8765` and `npm start` in `manager-ui/`.

## License

MIT. The manager's interface bundles Font Awesome Free (icons under CC BY 4.0, fonts under
the SIL OFL 1.1), the Tajawal typeface (SIL OFL 1.1), qrcode-generator (MIT) and xterm.js
(MIT).
[THIRD_PARTY_LICENSES.md](https://github.com/bn7ya/dbs/blob/main/THIRD_PARTY_LICENSES.md)
lists the license of every dependency.
