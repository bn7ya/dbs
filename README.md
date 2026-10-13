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

That is the backup library: everything a Django project needs to back up, restore and
validate. The rest comes as extras, so each machine installs only what it runs:

| You… | Install | You get |
|---|---|---|
| add `"dbs"` to a project's `INSTALLED_APPS` | `django-dbs` | **The backup library** — `manage.py dbs backup / restore / validate` |
| …and open `/admin/dbs/` as a superuser | `django-dbs[guard]` | **The panel** — backup frequency, restore, health and a tamper-evident audit trail, behind the session guard. `[guard]` adds the guard's anomaly detector |
| run `django_dbs run` on your own machine | `django-dbs[manager]` | **The DBS manager** — a local app that looks after many servers, pulls their backups and moves a project to a new server. Every action it has is also a command: `django_dbs server add`, `django_dbs backup take --all` |
| run `claude mcp add dbs -- django_dbs mcp` | `django-dbs[manager]` | **Claude at the controls** — ask Claude to add your servers, take and verify backups, set up plans and rehearse restores. It never sees a secret and cannot restore for real or delete anything |

`django-dbs[ssh]` adds `dbs.transports`, the SSH and SFTP API, for your own scripts.
`django-dbs[all]` installs the guard, the manager and the SSH API together. On the machine
that runs the manager, `pipx install "django-dbs[manager]"` keeps it in an environment of its
own.

Nothing else to install: no Node, no Docker, no Redis, no separate database server.

**Contents:**
[In your Django project](#1-in-your-django-project) ·
[The panel](#2-the-panel-at-admindbs) ·
[The DBS manager](#3-the-dbs-manager) ·
[Claude and MCP](#let-claude-control-the-manager) ·
[Moving to a new server](#moving-to-a-new-server) ·
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
pip install "django-dbs[guard]"   # the library, the panel and the session guard's detector
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

### A backup on standard output

```bash
python manage.py dbs backup --stream > /mnt/elsewhere/backup.dbs
```

`--stream` writes the backup to standard output and keeps the same bytes in
`DBS_BACKUP_DIR` (or `--output-dir`), named `PREFIX-YYYYMMDD-HHMMSSZ.dbs` with
`DBS_BACKUP_PREFIX` (or `--prefix`). Messages go to standard error, and its last line is a
JSON summary: `{"name", "size", "sha256"}`. When standard output breaks mid-way, the backup
still finishes on the server, the command exits 0 and the summary adds
`"kept_on_server": true`. The server keeps at most five streamed backups per prefix. This is
how the DBS manager takes a backup: a copy it did not receive waits on the server and is
collected the next time it connects.

---

## 2. The panel at `/admin/dbs/`

Once `dbs` is installed alongside `django.contrib.admin` and you have run `migrate`, the
panel is at **`/admin/dbs/`**. There is no `urls.py` change to make.

| Page | What it does |
|---|---|
| Dashboard | Schedule, health, recent backups and the guard at a glance |
| **Schedule** | Turn scheduled backups on, set how often and how many to keep, 1 to 5 |
| **Health** | Is the last backup recent enough, valid, still on disk? Is there disk space and a passphrase? |
| **Audit** | Every backup, restore, validation, prune, download and change made in the panel, sealed in a hash chain |
| Backups | Every backup this project wrote; **download** or **restore** any one kept in `DBS_BACKUP_DIR` |
| Take a backup | Writes one to `DBS_BACKUP_DIR` in the background, then offers it for download |
| Restore | Upload a `.dbs` file, with a dry run that changes nothing |
| **Connection** | What a DBS manager needs to reach this project, as one copyable snippet |
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

### Health

**Health** grades each check `ok`, `info`, `warn` or `error`:

* the last backup's age against the schedule: fine up to 1.5× the interval, late up to 3×,
  failing beyond that;
* the last validation, and whether the newest backup file is still on disk;
* whether `DBS_BACKUP_DIR` is writable and has room for two more backups;
* whether a passphrase is available for unattended backups;
* when the scheduler last checked in, and the most recent failure.

`python manage.py dbs health` prints the same report; `--json` gives it to a monitoring
system.

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
choose) and looks after the servers that run your Django projects. It connects to them over
SSH and:

* **pulls their DBS backups**, on demand or on a plan, and keeps the newest five of each;
* **backs up folders** as encrypted archives and **collects files** they already make;
* **browses their files** inside the folders you allow;
* **keeps every version of their `.env`**, encrypted, and can put one back;
* **restores a backup onto any server** — its own or a new one;
* **moves a project to a new server**, and puts the new server back if a move stops;
* **records every action** in its own audit trail, under the account that acted.

It is English and Arabic, right-to-left included.

### Start it

```bash
pip install "django-dbs[manager]"      # or: pipx install "django-dbs[manager]"
django_dbs run
```

If the shell says `django_dbs` is not recognized, pip put the script in a folder that is not
on your `PATH`. Run `python -m dbs.manager run` instead, or install it with pipx. Without the
`manager` extra, `django_dbs` prints the one `pip install` line it needs and stops.

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
| `--no-browser` | Do not open a browser; the address is printed either way |
| `--data-dir PATH` | Where the manager keeps everything (also `$DBS_MANAGER_HOME`) |
| `--database-url URL` | Use PostgreSQL or MySQL instead of SQLite (also `$DBS_MANAGER_DATABASE_URL`) |

The data folder holds the database, the backups it pulled and its log:

| System | Default data folder |
|---|---|
| Linux | `~/.local/share/django-dbs` (or `$XDG_DATA_HOME/django-dbs`) |
| macOS | `~/Library/Application Support/django-dbs` |
| Windows | `%LOCALAPPDATA%\django-dbs` |

`django_dbs paths` prints them, and where the sealing key is.

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
| **viewer** | See the servers, backups, plans, activity, `.env` key names and server files |
| **operator** | Check servers, take, verify and download backups, run plans, keep `.env` versions, download files, and rehearse restores and moves |
| **admin** | Add, change and remove servers, read and store backup passphrases, upload and delete backups, change plans, reveal and push `.env` versions, change files, and restore and move for real |
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
django_dbs createuser sara --role operator    # a first password; sara picks her own at first sign-in
django_dbs account list                       # role, active, two-factor, password expiry
django_dbs account role sara admin            # "master" hands the master role over
django_dbs account disable sara               # and enable
django_dbs account reset-2fa sara             # she sets it up again at her next sign-in
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

### Connect a server

**Add a server** walks you through it, one step at a time:

1. **Paste the connection snippet** (optional). On the server, open `/admin/dbs/` →
   *Connection* and press *Copy*, or run `python manage.py dbs connection --json`. The
   manager fills in every field from it.
2. **Confirm the host key.** The manager shows the fingerprint the server presents, and
   whether it matches the one in the snippet. Nothing connects until you confirm it.
3. **Choose how to sign in.** Let the manager create a key — it shows the one line to add to
   the server's `~/.ssh/authorized_keys` — or paste a key or a password.
4. **Choose the project.** The manager searches the server for `manage.py` as soon as the
   server is added and lists every project it finds. *Browse the server* opens the server's
   folders and files so you can pick the project, the backup folder, the allowed folders and
   the `.env` file instead of typing them. For the chosen project it tries every Python it
   can find — any virtualenv in or next to the project, `~/.virtualenvs`, then `python3` —
   and keeps the one that has django-dbs. A virtualenv or project it found by itself is run
   only when it belongs to the SSH user or root and no other account can write to it.
5. **Check versions.** The server's django-dbs is compared with the manager's. If the saved
   Python cannot import django-dbs, the check says so, shows the error, and offers the Python
   that has it with one click.
6. **Store the passphrase**, read from the server so you never retype it. Do it now, before
   the first backup: **a server's backup passphrase must never change**, because the backups
   taken with it would no longer open. A server added without it gets a random passphrase of
   the manager's own, which the backups the server writes by itself do not use.
7. **Take a test backup**, and watch it arrive.

Each server shows a connection dot — online, offline with when it was last seen, or not seen
yet. The manager reaches every server it has not heard from in five minutes, sends a
keepalive every 15 seconds on an open connection, and notices a dropped one instead of
waiting on it. Where the server has the `timeout` command, every remote command runs under
it and is stopped at its deadline; until a command whose end was not seen has run out its
time, the manager starts no backup, restore or move on that server (`server_settling`).

### What a server needs before the manager can reach it

| On the server | |
|---|---|
| An SSH user that owns the project, with the manager's key in `~/.ssh/authorized_keys` | the manager never uses `root` or a shell profile |
| The project, its virtualenv and `manage.py` | the manager runs `manage.py dbs …` with fixed arguments |
| `pip install django-dbs` and `"dbs"` in `INSTALLED_APPS`, migrated | 0.7 or later to take backups, which the manager streams with `dbs backup --stream`; 0.5 or later for health and the connection snippet; 0.2.2 or later to restore |
| A stable `SECRET_KEY` (or `DBS_PASSPHRASE`) in its `.env` | the backup passphrase comes from it, and must never change |
| `DBS_BACKUP_DIR`, writable by that user | where backups wait for the manager to collect them |

The project never contacts the manager and keeps nothing about it. A backup the manager
asks for is audited on the server like any other backup.

### Off-site copies

The manager pulls; the server never pushes. Every DBS backup run, on demand or from a plan:

1. **collects** the backups waiting in the server's backup folder under this server's or
   plan's name — a stream that broke last time, or copies kept there — skipping any it
   already holds with the same path, size and SHA-256;
2. **streams a fresh backup** to itself with `dbs backup --stream`, showing the bytes as they
   arrive;
3. **verifies** each one: the size and SHA-256 the server reported, then a full decryption;
4. **removes the server's copies** it recorded and verified, keeping the newest `keep_remote`
   of them (0 to 5, none by default).

When the connection breaks mid-stream, the run ends as *kept on the server*, not failed: the
server finished the backup and the next run collects it.

The manager keeps at most five good backups per server and plan, and never deletes the
newest one that passed verification. A file that fails verification is quarantined: kept
under a name that is not a backup name, with the reason, never restored and never counted.
The five newest quarantined files stay for you to inspect.

### A project that runs in Docker Compose

When the project's Django runs in a Docker Compose service, the manager runs every
`manage.py` command inside that service with `docker compose exec -T`, from the project
folder on the server. Choose **In a Docker Compose service** under *Where the project runs*,
in the wizard or in the server's settings, or from a terminal:

```bash
django_dbs server add shop --host shop.example.com --user deploy --ssh-password \
  --runtime compose --compose-service backend \
  --compose-file compose.yaml --compose-file compose.prod.yaml --project-dir /srv/shop
```

| Setting | |
|---|---|
| Project folder | the folder on the server that holds the Compose files; every command runs from it |
| Compose service | the service whose container runs Django, such as `backend` |
| Compose files | the files passed with `-f`, in order; with none, Docker uses the folder's default Compose file |
| Python and `manage.py` | paths inside the container, such as `python` and `manage.py` |

The SSH user must be able to run `docker compose` — usually as a member of the `docker` group,
which gives that user root on the server, so give it to the user that already deploys the
project. The service must be running, with django-dbs installed in its image, and must set
`DBS_BACKUP_DIR`.

When the search finds a Compose file in a folder that no other account can write to, it asks
Docker which services are running there and tries `python3` and `python` in each, so a
project whose image has django-dbs is found and filled in by itself. The check reports
Docker's version and whether the service is running, and names the service when django-dbs
is missing from it.

A backup streams out of the service and its copy waits in the service's `DBS_BACKUP_DIR`,
where the next run collects it if the stream broke. A restore copies the backup into the
container with `docker compose cp`, gives it to the container's user, restores it and
removes both copies. A move runs its `migrate` and restore steps inside the service too.

### The same manager from a terminal

Everything the interface does is also a `django_dbs` command. Both call the same code and
the same data folder, so a server added in a terminal appears in the browser, a backup the
browser took is listed in the terminal, and the **Activity** page records both under the
account that acted.

```bash
django_dbs server add shop --host shop.example.com --user deploy --ssh-password
django_dbs server add blog --host 203.0.113.7 --user deploy --key-file ~/.ssh/blog --project-dir /srv/blog
django_dbs server edit shop --runtime compose --compose-service backend
django_dbs server list
django_dbs backup take --all          # one after another, with a summary; exits 1 if one failed
django_dbs backup list --server shop
django_dbs plan add shop nightly --kind dbs --every 1440 --keep 5
django_dbs server remove blog
```

`server add` goes through the wizard's steps. It shows the host key fingerprint and asks you
to confirm it (`--host-key` or `--yes` from a script), finds the project and the Python that
has django-dbs, saves them and checks the server. `--generate-key` prints the line to add to
`authorized_keys` instead.

| Area | Commands |
|---|---|
| `server` | `list` · `show` · `add` · `edit` · `remove` · `check SERVER… \| --all` · `discover [--save]` · `browse [PATH]` · `public-key` · `host-key` · `confirm-host-key ID` · `passphrase` · `capture-passphrase` |
| `backup` | `list` · `take SERVER… \| --all` · `verify` · `restore --mode merge\|replace [--to SERVER] [--real]` · `download [-o PATH]` · `upload` · `delete` · `undo-delete` |
| `plan` | `list` · `show` · `add` · `edit` · `remove` · `run` |
| `activity` | `list [--server] [--action] [--status] [--limit]` · `show` |
| `env` | `list` · `pull` · `compare` · `reveal` · `push` |
| `files` | `list` · `download` · `upload` · `mkdir` · `delete` |
| `redeploy` | `start --from SERVER --to SERVER [--backup ID] [--env ID] [--flush] [--real]` · `revert MOVE_ID [--real]` |

A server is named by its name or its id; a backup, plan or `.env` version by the id that
`list` prints. Every command takes `--json`, which prints exactly what the web API returns.
`server list` and `server check` show each server's connection, and a long job prints a
progress line every 30 seconds.

The terminal follows the interface's rules. Commands act as a manager account: the only one,
or the one named with `--as NAME`, within that account's role. An action the interface
protects with your password — changing a checked server's paths, revealing a passphrase or a
`.env`, a plan that keeps fewer backups, downloading what the manager keeps encrypted,
deleting a backup, removing a server, restoring or moving for real — asks for it here too, or
reads it with `--password-stdin`. Secrets are typed at a prompt or read from stdin, never
passed as arguments. Downloads are saved readable by you alone. Removing a server also asks
you to type its name unless you pass `--yes`. While the account's password has expired, every
command says so on standard error.

A command that takes a backup waits for it and prints the result. It can run while
`django_dbs run` is open: both take the same per-server lock, so a scheduled backup and one
from the terminal never run on one server at the same time. Starting the manager frees the
locks of jobs whose process is gone.

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
shop.example.com, user deploy, and back up every server"*.

What Claude can do:
- see the overview, servers, backups, plans, activity, `.env` versions (key names only) and
  server files;
- add a server, with an SSH password, a key file on this machine (the manager reads the file,
  Claude only names it), or a new key — once **you** have confirmed its host key. Claude reads
  the key and shows you the fingerprint; you confirm it on the **Servers** page or with
  `django_dbs server confirm-host-key ID` in a terminal. Claude cannot confirm it itself, and a
  key waits ten minutes for you;
- change a server's name or address, check servers, find a project and its Python, and store
  a new server's backup passphrase before its first backup;
- take, verify and save backups, add and run plans, keep more backups, and keep `.env`
  versions;
- rehearse a restore, a move to another server, or putting the new server back after a move
  that stopped. A rehearsal changes nothing.

What Claude cannot do: reveal a passphrase or a `.env` value, restore, move or revert for
real, push a `.env`, make a plan keep fewer backups, save a file the manager keeps encrypted,
remove a server, delete backups or files, or pin or re-pin a host key you did not confirm.
The MCP server never takes your account password, so anything the interface protects with
it — changing a checked server's paths, archive and collect plans — comes back to you to do
in the interface or the terminal. Everything Claude does is in **Activity** under the account
it acts as.

An SSH password you give Claude passes through the conversation. Prefer a key file or a new
key when that matters to you.

### Backups, plans, files and `.env`

Each server has tabs for **Backups** (take one now, upload one, verify, download, restore),
**Plans** (a DBS backup, a folder archive or a file collection on a schedule, keeping 1 to 5
here and 0 to 5 on the server), **Files** (browse, upload, download inside the allowed
folders) and **Environment** (every version of the `.env`, compared side by side, revealed
only after you type your password, and pushed back when you need it). The **Dashboard**
shows every server's connection, last backup, checks, next plan and recent failures;
**Activity** is the full audit trail, and a running job shows whether its connection is
alive and how much it has moved.

A plan that keeps fewer backups than before deletes the oldest on its next run, so changing
it asks for your password. Two plans of one server cannot share a name that differs only in
case or punctuation. Downloading a folder archive, a collected or an uploaded file decrypts
it, and so does downloading a `.env` through the Files tab, so each asks for your password
and the browser follows a one-time link that lasts a minute. Deleting a backup or a server
asks for it too.

---

## Moving to a new server

A move stands the project up on a new server that already runs its code with the same
environment. The manager carries the data and the `.env` across, and keeps a way back.

1. Prepare the new machine: check out the project's code, create its virtualenv,
   `pip install -r requirements.txt` (with `django-dbs` in it), with the same settings.
2. In the manager, **add the new server** with the wizard.
3. Open the old server and choose **Move to another server**. Pick the new server, the `.env`
   version to push, whether to replace the new server's data instead of merging, and the
   backup to restore if the old server does not answer (its newest by default, or none to stop
   instead).
4. Run the **rehearsal**. It checks the new server, asks the old one whether it answers, and
   restores the backup in a transaction it rolls back. Nothing changes on either server. A
   rehearsal onto a server whose database is not migrated yet checks the backup in the
   manager instead — that it is whole and opens with the old server's passphrase.
5. Run it for real: type your password and the new server's name. The manager:
   1. checks the new server;
   2. backs up the old server now, when it answers, and keeps that backup with no copy left
      on the old server; when it does not answer, it uses the backup you chose;
   3. records the new server's `.env` as a version;
   4. takes a safety backup of the new server's data, when its database is migrated;
   5. pushes the `.env`, runs `migrate`, restores the backup with the old server's
      passphrase, and checks the new server again.

The `.env` goes before the restore on purpose: it carries the old `SECRET_KEY`, which the
restored project needs for its sessions and its encrypted fields. Every step is in the audit
trail.

When a step after the `.env` push fails, the move stops and names that step. The move page
then offers **Revert the new server**: it pushes the recorded `.env` back and restores the
safety backup, replacing what the move left there. Rehearse the revert first; a real revert
needs your password and the new server's name. From a terminal:

```bash
django_dbs redeploy start --from old --to new            # a rehearsal
django_dbs redeploy start --from old --to new --real
django_dbs redeploy revert 412 --real                    # 412: the move's activity number
```

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
`DBS_MANAGER_DATABASE_URL`, `import` loads into an empty database instead.

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
permissions, admin log, sessions, and DBS's own tables). Prefix a label with `-` to back up
one the defaults skip, an unmanaged model included:
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
> set a new `DBS_PASSPHRASE`, or store a different passphrase for the server in the DBS
> manager, and every older backup stops opening. Nobody can open a backup whose passphrase
> is lost.

**Rotating `SECRET_KEY`:** keep the old value in `SECRET_KEY_FALLBACKS`. DBS tries every
fallback when restoring, so a rotation done the supported Django way does not strand old
backups. Archive `python manage.py dbs key --show` before you rotate.

The DBS manager stores each server's backup passphrase, sealed, and hands it to the server
on standard input for every backup and restore. Store it once, while you add the server and
before its first backup — *Store the passphrase* in the wizard, or
`django_dbs server capture-passphrase SERVER` — and never replace it afterwards.

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

The forest needs scikit-learn, which `django-dbs[guard]` installs. Without it the guard
scores with its rules alone. `manage.py check` warns about the three ways a guard can be set
up wrong:

| Check | Means |
|---|---|
| `dbs.security.W001` | `DBS_TRUST_FORWARDED_FOR` is on but `DBS_TRUSTED_PROXIES` names no proxy network |
| `dbs.security.W002` | `DBSSecurityMiddleware` runs before `AuthenticationMiddleware`, so it scores nothing |
| `dbs.security.W003` | scikit-learn is missing; `pip install "django-dbs[guard]"` |

---

## Working with AI assistants

```bash
python manage.py dbs ai            # writes .claude/skills/django-dbs/
python manage.py dbs ai --agents   # also appends a section to AGENTS.md
python manage.py dbs ai --check    # CI: fail if the installed copy has drifted
```

The instructions live inside the installed package under `dbs/ai/`, so they always match
the version you have.

To let Claude operate the manager itself — add servers, take and verify backups, set up
plans — connect its MCP server:

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
python manage.py dbs backup --stream    [--prefix P] [--output-dir DIR] [--passphrase-stdin]
python manage.py dbs restore INPUT      [--dry-run] [--flush] [--no-data] [--no-files] [--database]
python manage.py dbs validate INPUT     [--passphrase]
python manage.py dbs schedule           [--once] [--interval 6h --output-dir DIR --keep 1-5]
python manage.py dbs health             [--json]
python manage.py dbs audit verify
python manage.py dbs connection         [--json]
python manage.py dbs key                [--show]
python manage.py dbs security ACTION    [USERNAME]
python manage.py dbs ai                 [--agents] [--check] [--print]
python manage.py dbs upgrade            [--check] [--self [--to X.Y.Z] [--yes] [--system-python]] [--backups DIR] [--offline]

django_dbs run                          [--port] [--host] [--trusted-proxy CIDR] [--allow-insecure-http] [--no-browser]
django_dbs export [FILE]                [--with-backups] [--passphrase-stdin]
django_dbs import FILE                  [--replace] [--yes] [--passphrase-stdin]
django_dbs createuser NAME              [--role admin|operator|viewer] [--password-stdin]
django_dbs password NAME                [--password-stdin]
django_dbs account  list|role|disable|enable|reset-2fa
django_dbs paths · --version

django_dbs server  list|show|add|edit|remove|check|discover|browse|public-key|host-key|confirm-host-key|passphrase|capture-passphrase
django_dbs backup  list|take|verify|restore|download|upload|delete|undo-delete
django_dbs plan    list|show|add|edit|remove|run
django_dbs activity list|show  ·  django_dbs env list|pull|compare|reveal|push
django_dbs files   list|download|upload|mkdir|delete  ·  django_dbs redeploy start|revert
                                        [--as NAME] [--json] [--password-stdin]
django_dbs mcp                          [--as NAME]
```

Every `django_dbs` command takes `--data-dir`, and every one but `paths` takes
`--database-url`. `django_dbs AREA VERB --help` lists each command's options, and
`python -m dbs.manager COMMAND` is the same as `django_dbs COMMAND`.

`dbs security` takes `status`, `unlock USER`, `policy`, `retrain`, `reset-baseline USER`,
`events` and `purge`; `status` shows the idle timeout and the state of the anomaly model.

`dbs schedule` with no plan flags follows the panel's schedule; with `--interval`,
`--output-dir`, `--prefix` or `--keep` it runs that plan instead. `python manage.py
django-dbs` is the same umbrella under its older name, and `dbs_backup`, `dbs_restore`,
`dbs_validate` and `dbs_schedule` still work.

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

`dbs.transports` needs `django-dbs[ssh]`. Host keys are verified and unknown hosts are
rejected by default: pin the one key you expect with `host_key`, or point `known_hosts` at a
file. `fetch_host_key(host)` reads a key so you can compare its `fingerprint` with the one
the server prints (`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`) before you store its
`line`. A server that presents a different key raises `HostKeyError`. A session sends a
keepalive every 15 seconds, notices a dropped connection, and stops a remote command after
`command_timeout` (6 hours by default).

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
* Every server credential, passphrase, `.env` version and archive in the manager is sealed
  with AES-256-GCM under its sealing key, kept in the system keychain where one works, and
  never returned by any page or API.
* SSH host keys are verified by default; the manager pins exactly the key a person
  confirmed. Remote commands are built from fixed argument lists, and passphrases travel on
  standard input, never on a command line.

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

**`django_dbs` says it needs `django-dbs[manager]`.** Install it:
`pip install "django-dbs[manager]"`.

**`django_dbs run` shows "the interface was not built".** You installed from a source
checkout. Install from PyPI, or build it once with `scripts/build_manager_ui.sh`.

**`django_dbs` is not recognized / command not found.** pip installed the script into a
folder that is not on your `PATH`, common with Windows user installs and
`pip install --user`; pip prints that folder in a warning during the install. Add it to
`PATH`, or run `python -m dbs.manager run` instead.

**`django_dbs run` will not start: the system keychain refused.** Unlock the keychain and
start again, or set `DBS_MANAGER_KEY_STORE=file` to keep the sealing key in the data folder.

**The manager cannot reach a server.** Re-run the wizard's *Check* step, or
`django_dbs server check SERVER`: it names whether the SSH login, the host key, the project
path or the server's django-dbs version is the problem. A server whose django-dbs is older
than 0.7 answers `dbs_too_old` when a backup is taken; upgrade it.

**A terminal command says "pick the account to act as".** The manager has more than one
account; add `--as NAME`.

**A command or a page says it needs another role.** Your account's role does not allow it.
Ask the master account for a higher one.

**A terminal command says it asks for a secret to be typed.** It ran without a terminal, as
from cron. Pass the password on stdin with `--password-stdin` (or the SSH password with
`--ssh-password-stdin`), and `--yes` for confirmations.

**The manager says django-dbs is "Not found" on a server that has it.** The manager runs the
Python saved for that server over a non-interactive SSH login, which loads no virtualenv. The
check names the Python it used and the error it got, and offers the Python where django-dbs
is installed; choose *Use this Python*. Or open the server's settings and pick the project
again with *Browse the server*.

**Backups taken by the manager fail verification.** They are quarantined, never restored.
The usual cause is a backup passphrase in the manager that is not the server's: the
passphrase must be the one its backups were taken with.

---

## Upgrading

Pin the release in your requirements or lock file and reinstall, with the extras you use:

```bash
pip install "django-dbs[guard]==X.Y.Z"
python manage.py dbs upgrade
```

It applies pending DBS migrations itself, and prints, with the exact line to add, anything
that means editing your own code. `--check` changes nothing and exits non-zero when
something needs doing, for CI. Inside a virtual environment, `dbs upgrade --self` installs
the newest release (or `--to X.Y.Z`) with the extras installed there: it prints the pinned
`pip install` command and asks first (`--yes` answers for a script), names the requirement
files to pin it in too, leaves a source checkout alone, and an interpreter outside a virtual
environment unless you add `--system-python`.

`--backups DIR` reads old backups and converts any written in an older format into a new
file beside the original. Nothing in DBS ever deletes or overwrites a backup.

**From 0.4.x:** `dbs upgrade` applies the audit and schedule migrations. If you set
`DBS_SCHEDULE_INTERVAL`, turn the schedule on once in the panel, or keep running
`dbs schedule --interval …` as before. Projects behind uWSGI without threads should set
`DBS_SCHEDULER = "command"`.

**From 0.5.x:** `dbs schedule` with no flags now always follows the panel. If its schedule is
off, the command waits for it instead of backing up every 24 hours; turn the schedule on, or
pass `--interval`. `dbs upgrade` says so when it applies. The manager applies its own new
migrations the next time any `django_dbs` command starts.

**From 0.6.x:** `pip install django-dbs` is now the backup library alone. Add the extras you
use — `[guard]` for the session guard's detector, `[manager]` for `django_dbs`, `[ssh]` for
`dbs.transports`, or `[all]` — then run `dbs upgrade`. It applies the migration that seals
the audit trail and drops the SFTP targets, and reports each of these:

| Step | What it says, and what to do |
|---|---|
| dependencies | numpy is now required, for the Reed-Solomon parity |
| guard extra | `DBSSecurityMiddleware` is on but scikit-learn cannot be imported: `pip install "django-dbs[guard]"` |
| manager extra · manager keychain | Whether `django_dbs` can run here, and that its sealing key moves to the system keychain |
| off-site copies | The panel no longer pushes backups. `DBS_SSH_TARGETS`, `DBS_SCHEDULE_PUSH_TARGET`, `DBS_SCHEDULE_KEEP_REMOTE` and `DBS_ADMIN_CONSOLE_SHELL` do nothing; delete them, and add this server to a DBS manager, which pulls its backups. The SFTP targets the panel held are named in the audit trail |
| dbs-client | `dbs-client` is gone. Install the manager on your own machine and add each server from its config with `django_dbs server add` |
| retention | The server keeps at most five backups: a schedule keeping more is lowered to 5, and `DBS_SCHEDULE_KEEP` above 5 is refused |
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

## Development

```bash
pip install -e ".[dev]"
scripts/test.sh                       # the library suite, then the manager suite
DBS_TEST_HOUR=3 pytest                # the guard scores time of day; pin it
scripts/build_manager_ui.sh           # build the manager's interface into the package (needs Node)
```

The manager's interface lives in `manager-ui/` (Angular, Angular Material). For live
reload, run `django_dbs run --no-browser --port 8765` and `npm start` in `manager-ui/`.

## License

MIT. The manager's interface bundles Font Awesome Free (icons under CC BY 4.0, fonts under
the SIL OFL 1.1), the Tajawal typeface (SIL OFL 1.1) and qrcode-generator (MIT).
[THIRD_PARTY_LICENSES.md](https://github.com/bn7ya/dbs/blob/main/THIRD_PARTY_LICENSES.md)
lists the license of every dependency.
