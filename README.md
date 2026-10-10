# DBS — Django Backup Solution

> 🚧 **Under development.** DBS is in active development and its API may change.
>
> Created by **Sudum Technology — Research and Development sector**.
> Our very tiny contribution to this world.

DBS backs up a Django project into **one encrypted file**: rows, relations and files
together. The file is *redundant* and *self-healing*. It holds **two copies** of your data
plus **Reed-Solomon parity**, so silent corruption is detected and repaired when you
restore, instead of quietly poisoning the data you were relying on.

## One install, three ways to use it

```bash
pip install django-dbs
```

What you get depends only on where you use it:

| You… | You get |
|---|---|
| add `"dbs"` to a project's `INSTALLED_APPS` | **The backup library** — `manage.py dbs backup / restore / validate` |
| …and open `/admin/dbs/` as a superuser | **The panel** — backup frequency, restore, health and an audit trail, with no extra setup |
| run `django_dbs run` in a terminal | **The DBS manager** — a local app that looks after many servers, pulls their backups and moves a project to a new server when the old one goes down |

Nothing else to install: no Node, no Docker, no Redis, no separate database server.

**Contents:**
[In your Django project](#1-in-your-django-project) ·
[The panel](#2-the-panel-at-admindbs) ·
[The DBS manager](#3-the-dbs-manager) ·
[When a server goes down](#when-a-server-goes-down) ·
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
| A **stable `SECRET_KEY`** | DBS derives the backup passphrase from it. Change it only with the old value kept in `SECRET_KEY_FALLBACKS`, or older backups can no longer be opened. |
| **`DBS_BACKUP_DIR`**, writable by the app | Where scheduled backups are kept, and where the panel restores and checks them from. |
| `django.contrib.admin` mounted | The panel lives inside the admin. |
| A superuser | The panel is for superusers only. |
| Python 3.9+ and Django 4.2+ | |

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
    # Django's defaults…
    "dbs.security.middleware.DBSSecurityMiddleware",
]

DBS_BACKUP_DIR = os.environ.get("DBS_BACKUP_DIR", str(BASE_DIR / "backups"))
DBS_SCHEDULER = os.environ.get("DBS_SCHEDULER", "thread")
```

`DBS_PASSPHRASE` is read straight from the environment by DBS, so it needs no line in
`settings.py`. If you already use `django-environ` or `python-dotenv`, use them instead of
the loop above.

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

---

## 2. The panel at `/admin/dbs/`

Once `dbs` is installed alongside `django.contrib.admin` and you have run `migrate`, the
panel is at **`/admin/dbs/`**. There is no `urls.py` change to make.

| Page | What it does |
|---|---|
| Dashboard | Schedule, health, recent backups, SFTP targets and the guard at a glance |
| **Schedule** | Turn scheduled backups on, set how often and how many to keep |
| **Health** | Is the last backup recent enough, valid, still on disk? Is there disk space and a passphrase? |
| **Audit** | Every backup, restore, validation, prune and setting change, with its outcome |
| Backups | Every backup this project wrote; **restore** any one kept in `DBS_BACKUP_DIR` |
| Take a backup | Download one now, or push it straight to an SFTP target |
| Restore | Upload a `.dbs` file, with a dry run that changes nothing |
| **Connection** | What a DBS manager needs to reach this project, as one copyable snippet |
| SFTP targets · Console | Off-site servers and a fixed set of actions to run on them |
| Security · Wiki | The session guard, and the full manual |

**Superusers only.** There is deliberately no grantable permission for it: the panel can
download and overwrite your entire database. On your first visit a short wizard asks which
networks you log in from and how strict the guard should be.

### Backup frequency

Open **Schedule**, tick *enabled*, and pick an interval (`30m`, `6h`, `1d`) and how many
backups to keep. That is all: the schedule runs inside your web workers. On the first
request a worker serves, a small background thread starts and checks once a minute whether
a backup is due. Every worker runs one, and a lease in the database makes sure exactly one
backup is taken per interval however many workers or servers you run.

Prefer a separate process? Set `DBS_SCHEDULER = "command"` and run
`python manage.py dbs schedule` under systemd. It follows the same panel setting. Set
`DBS_SCHEDULER = "off"` to switch scheduling off entirely.

| Deployment | Use |
|---|---|
| gunicorn, uWSGI with `--enable-threads`, Daphne, uvicorn | `"thread"` (default) |
| uWSGI without threads, or several hosts each with its own local `DBS_BACKUP_DIR` | `"command"`, one `dbs schedule` process |
| Serverless, or backups taken only from a DBS manager | `"off"` |

Backups are named `prefix-YYYYMMDD-HHMMSSZ.dbs` in UTC. Retention only ever considers files
that match that pattern and prefix; anything else in the directory is left alone.

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

Each backup, restore, validation, retention prune, push and schedule change writes one row:
what happened, to which file, its size and SHA-256, how long it took and whether it
succeeded, with an error code when it did not. A backup records itself the same way however
it was started — the panel, the schedule, `manage.py`, cron or an SSH session — so the
trail describes the process, never who asked for it. Writing the trail can never fail a
backup: if the database refuses the row, the backup still completes and the problem is
logged.

### Restore from the server side

Every backup in `DBS_BACKUP_DIR` has a **restore** link on its row. The page opens with
*Dry run* ticked; a real restore needs the file name typed out. *Replace instead of merge*
clears the backed-up tables first. See [Restoring](#restoring) for what a restore does.

---

## 3. The DBS manager

The manager is a small application that runs on your own machine (or any machine you
choose) and looks after the servers that run your Django projects. It connects to them over
SSH and:

* **takes their DBS backups**, on demand or on a plan, keeps the newest N, and **pulls a
  copy** into its own storage;
* **backs up folders** as encrypted archives and **collects files** they already make;
* **browses their files** inside the folders you allow;
* **keeps every version of their `.env`**, encrypted, and can put one back;
* **restores a backup onto any server** — its own or a new one;
* **records every action** in its own audit trail.

It is English and Arabic, right-to-left included.

### Start it

```bash
pip install django-dbs
django_dbs run
```

If the shell says `django_dbs` is not recognized, pip put the script in a folder that is not
on your `PATH`. Run `python -m dbs.manager run` instead, or install with
`pipx install django-dbs`.

The first run creates a data folder, a local SQLite database and a secret key, starts the
manager on `http://127.0.0.1:8765` and opens your browser at a one-time setup page. Choose a
username and password; they are stored, hashed, in that local database. The next
`django_dbs run` opens straight to the sign-in page. Running it again while it is already
running just opens the browser on the running one.

| Option | Meaning |
|---|---|
| `--port 8765` | Port to listen on. If it is taken, a free one is chosen |
| `--host 127.0.0.1` | Address to listen on. Anything but loopback prints a warning |
| `--no-browser` | Do not open a browser; the address is printed either way |
| `--data-dir PATH` | Where the manager keeps everything (also `$DBS_MANAGER_HOME`) |
| `--database-url URL` | Use PostgreSQL or MySQL instead of SQLite (also `$DBS_MANAGER_DATABASE_URL`) |

The data folder holds the database, `keys/secret.key`, the backups it pulled and its log:

| System | Default data folder |
|---|---|
| Linux | `~/.local/share/django-dbs` (or `$XDG_DATA_HOME/django-dbs`) |
| macOS | `~/Library/Application Support/django-dbs` |
| Windows | `%LOCALAPPDATA%\django-dbs` |

`django_dbs paths` prints them. `django_dbs createuser NAME` and `django_dbs password NAME`
manage accounts without a browser; add `--password-stdin` to script them.

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
6. **Store the passphrase** (optional), read from the server so you never retype it.
7. **Take a test backup**, and watch it arrive.

### What a server needs before the manager can reach it

| On the server | |
|---|---|
| An SSH user that owns the project, with the manager's key in `~/.ssh/authorized_keys` | the manager never uses `root` or a shell profile |
| The project, its virtualenv and `manage.py` | the manager runs `manage.py dbs …` with fixed arguments |
| `pip install django-dbs` and `"dbs"` in `INSTALLED_APPS`, migrated | 0.5 or later for health and the connection snippet; 0.2.2 or later to restore |
| A stable `SECRET_KEY` (or `DBS_PASSPHRASE`) in its `.env` | the backup passphrase comes from it |
| `DBS_BACKUP_DIR`, writable by that user | where the backups the manager asks for are written |

The project never contacts the manager and keeps nothing about it. A backup the manager
asks for is audited on the server like any other backup.

### Backups, plans, files and `.env`

Each server has tabs for **Backups** (take one now, upload one, verify, download, restore),
**Plans** (a DBS backup, a folder archive or a file collection on a schedule, keeping the
newest N here and on the server), **Files** (browse, upload, download inside the allowed
folders) and **Environment** (every version of the `.env`, compared side by side, revealed
only after you type your password, and pushed back when you need it). The **Dashboard**
shows every server's last backup, checks, next plan and recent failures; **Activity** is
the full audit trail.

---

## When a server goes down

Keep three things on the manager — the server's DBS backups, its `.env` versions and, if
you use them, its folder archives — and you can stand the project up somewhere else:

1. Prepare the new machine: check out the project's code, create its virtualenv,
   `pip install -r requirements.txt` (with `django-dbs` in it).
2. In the manager, **add the new server** with the wizard.
3. Open the old server and choose **Move to another server**. Pick the new server, the
   backup, the `.env` version and any archives.
4. Run the **rehearsal**. It checks the new server and restores in a transaction it rolls
   back, so nothing changes.
5. Run it for real: type your password and the new server's name. The manager pushes the
   `.env`, runs `migrate`, restores the backup with the old server's passphrase, unpacks the
   archives into the new server's project folder (even when it lives at a different path)
   and checks the result. Every step is in the audit trail.

A rehearsal onto a server whose database is still empty cannot rehearse the restore itself,
so it checks the backup in the manager instead — that it is whole and opens with the old
server's passphrase — and the move for real migrates before it restores.

The `.env` goes first on purpose: it carries the old `SECRET_KEY`, which the restored
project needs for its sessions and its encrypted fields.

### Moving the manager itself

The manager is just as portable:

```bash
django_dbs export manager.dbs                  # database and keys, one encrypted DBS file
django_dbs export manager.dbs --with-backups   # also every backup it pulled
django_dbs import manager.dbs                  # on the new machine, before the first run
```

`export` asks for a passphrase twice; keep it with the file. `import` refuses to overwrite
a manager that already holds servers unless you pass `--replace`, and refuses while a
manager is running on that data folder.

---

## Pulling backups from a terminal

`dbs-client` is the manager without the interface: it asks a server for a fresh backup and
downloads it over one SSH connection, from a script or cron.

```bash
dbs-client init                 # writes dbs-client.toml, mode 600
$EDITOR dbs-client.toml
dbs-client test-connection
dbs-client backup
```

```toml
[defaults]
server = "production"
dest = "~/dbs-backups"
keep = 14

[servers.production]
host = "app.example.com"
username = "deploy"
key_filename = "~/.ssh/production.pem"
known_hosts = "~/.ssh/known_hosts"
project_dir = "/srv/myproject"
python = "/srv/myproject/.venv/bin/python"
django_settings_module = "myproject.settings.production"
remote_dir = "/var/backups/myproject"
passphrase_env = "DBS_PASSPHRASE"
```

| Command | What it does |
|---|---|
| `init` | Write a starter config (mode 600, never overwrites). `--print` to stdout |
| `test-connection` | Check auth, host key policy, remote directory, server version |
| `list` | List remote backups with size and time |
| `backup` | Make a backup on the server and download it |
| `pull NAME` / `pull --latest` | Download a backup that already exists |
| `push PATH` | Upload a local backup file to the server |
| `prune` | Apply retention locally, remotely, or both. `--dry-run` first |
| `schedule` | Repeat `backup` on an interval. `--once` for one cycle |
| `validate PATH` | Check a local backup file — no Django project needed |

Downloads stream to a `.part` file and are renamed only once complete. The passphrase never
appears in a command line: it travels down the SSH channel to `--passphrase-stdin`. An
unrecognised config key is an error, and a config holding a literal secret that other users
can read is refused.

<details>
<summary>All config keys</summary>

Anything under `[defaults]` applies to every server unless that server overrides it. Pick a
server with `--server NAME`. Any secret can be read from an environment variable by adding
`_env` to the key name.

| Key | Meaning |
|---|---|
| `host` · `username` · `port` | Where to connect. `host` and `username` required |
| `key_filename` | `.pem` or OpenSSH private key. `~` is expanded |
| `key_passphrase` · `key_passphrase_env` | For an encrypted key file |
| `password` · `password_env` | Password authentication |
| `use_agent` | Use ssh-agent (default `true`) |
| `known_hosts` · `host_key` · `auto_add_host_key` | Host key verification. `host_key` pins one key, `"<type> <base64>"` |
| `connect_timeout` | Seconds to wait for the SSH handshake |
| `remote_dir` | Where backups live on the server. Created if missing |
| `project_dir` · `python` · `manage` · `django_settings_module` | How to run `manage.py` remotely |
| `env` | Extra environment variables for the remote command |
| `passphrase` · `passphrase_env` | The backup encryption passphrase |
| `passphrase_transport` | `stdin` (default) or `env` |
| `database` | Database alias to back up |
| `dest` · `prefix` · `keep` · `keep_remote` · `interval` | Local defaults |
| `exec_timeout` | Seconds to allow the remote backup to run |

</details>

---

## Off-site copies over SFTP

Define a server **in settings**, for automation:

```python
DBS_SSH_TARGETS = {
    "offsite": {
        "host": "backups.example.com",
        "username": "deploy",
        "key_filename": "/home/deploy/.ssh/id_ed25519",
        "known_hosts": "/home/deploy/.ssh/known_hosts",
        "remote_dir": "/var/backups/myproject",
    }
}
```

**Or in the panel**, under *SFTP targets*, where passwords and private keys are encrypted
at rest and never shown again once saved. Choose it as the schedule's *push target* to copy
every scheduled backup there, keeping `keep_remote` of them.

Host keys are verified and unknown hosts are **rejected by default**. Point `known_hosts`
at a file, pin the one key you expect with `host_key`, or set `auto_add_host_key` to trust
whatever key the server presents on first contact. To pin a key, read it and compare its
fingerprint with the one the server prints (`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`):

```python
from dbs.transports import fetch_host_key

key = fetch_host_key("backups.example.com")
print(key.fingerprint)   # SHA256:…, compare it before trusting it
key.line                 # "ssh-ed25519 AAAA…", store it as host_key
```

---

## Restoring

```bash
python manage.py dbs restore backup.dbs --dry-run   # rehearse, change nothing
python manage.py dbs restore backup.dbs             # merge into what's there
python manage.py dbs restore backup.dbs --flush     # replace instead of merge
```

* **It merges by default.** Rows created after the backup was taken are kept. `--flush`
  clears the backed-up models first, children before parents, in the same transaction.
* **The load is one transaction.** If anything fails midway the database is untouched.
* **File writes are confined** to `DBS_RESTORE_ROOTS` (or `DBS_FILE_ROOTS` if unset).
* **Migration drift is reported**, naming the apps that moved on since the backup.
* **Sequences are reset**, so the next row your project creates does not collide.

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
relations. Every row is backed up, including rows the default manager hides. Register a
model only to override that, in a `dbs.py` inside your app:

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
    file_roots = ["/srv/myapp/uploads"]           # extra file trees
```

`DBS_EXCLUDE_MODELS` skips models in addition to the built-in exclusions (content types,
permissions, admin log, sessions, and DBS's own tables). Prefix a label with `-` to back up
one the defaults skip: `DBS_EXCLUDE_MODELS = ["myapp.AuditRow", "-sessions.Session"]`.

---

## Passphrases

DBS derives the backup passphrase from `SECRET_KEY`, domain separated so it is never the
same bytes Django uses for sessions and tokens. Order of precedence:

1. `--passphrase` or `--passphrase-stdin` on the command line
2. The `DBS_PASSPHRASE` environment variable
3. The `DBS_PASSPHRASE` setting
4. Derived from `SECRET_KEY`

**Rotating `SECRET_KEY`:** keep the old value in `SECRET_KEY_FALLBACKS`. DBS tries every
fallback when restoring. A backup encrypted under a key you lost, and did not keep, cannot
be opened by anyone.

---

## The session guard

The panel can export and overwrite your whole database, so every admin request from a
superuser is scored — time of day, request rate, how risky the action is, session age,
failed logins, and whether the network and browser are familiar — by an `IsolationForest`
shipped pre-trained and refitted on the account's own history. A high enough score ends
that account's sessions.

**If it locks you out, a shell always wins:** `python manage.py dbs security unlock alice`.

Loosen it with `DBS_TRUSTED_NETWORKS`, `DBS_ANOMALY_ENFORCE = False`, or a more relaxed level
in the setup wizard. `DBS_GEOLOCATION = True` adds browser location, which can only ever
raise a score. Free-form remote commands in the console stay off unless
`DBS_ADMIN_CONSOLE_SHELL = True`.

---

## Working with AI assistants

```bash
python manage.py dbs ai            # writes .claude/skills/django-dbs/
python manage.py dbs ai --agents   # also appends a section to AGENTS.md
python manage.py dbs ai --check    # CI: fail if the installed copy has drifted
```

The instructions live inside the installed package under `dbs/ai/`, so they always match
the version you have.

---

## Command reference

```bash
python manage.py dbs                    # overview
python manage.py dbs backup OUTPUT
python manage.py dbs restore INPUT      [--dry-run] [--flush] [--no-data] [--no-files]
python manage.py dbs validate INPUT     [--passphrase]
python manage.py dbs schedule           [--once] [--interval 6h --output-dir DIR --keep N]
python manage.py dbs health             [--json]
python manage.py dbs connection         [--json]
python manage.py dbs key                [--show]
python manage.py dbs security ACTION    [USERNAME]
python manage.py dbs ai                 [--agents] [--check] [--print]
python manage.py dbs upgrade            [--check] [--self] [--backups DIR] [--offline]

django_dbs run                          [--port] [--host] [--no-browser] [--data-dir] [--database-url]
django_dbs export [FILE]                [--with-backups] [--passphrase-stdin]
django_dbs import FILE                  [--data-dir] [--replace] [--passphrase-stdin]
django_dbs createuser NAME              [--password-stdin]
django_dbs password NAME                [--password-stdin]
django_dbs paths · --version

dbs-client COMMAND                      [--server NAME] [--config PATH]
```

`python -m dbs.manager COMMAND` is the same as `django_dbs COMMAND`, and
`python -m dbs.client COMMAND` the same as `dbs-client COMMAND`.

`dbs schedule` with no plan flags follows the panel's schedule; with `--interval`,
`--output-dir`, `--keep`, `--push` or `--keep-remote` it runs that plan instead, as it always
has. `python manage.py django-dbs` is the same umbrella under its older name, and
`dbs_backup`, `dbs_restore`, `dbs_validate` and `dbs_schedule` still work.

---

## Settings reference

Everything is optional. DBS works with none of these set.

| Setting | Purpose |
|---|---|
| `DBS_BACKUP_DIR` | Where scheduled backups are kept, restored from and checked |
| `DBS_SCHEDULER` | `"thread"` (default), `"command"` or `"off"` |
| `DBS_SCHEDULE_INTERVAL` · `DBS_SCHEDULE_KEEP` · `DBS_SCHEDULE_KEEP_REMOTE` | Seed the panel's first schedule, and the defaults for `dbs schedule` with flags |
| `DBS_BACKUP_PREFIX` | Filename prefix, so several projects can share a directory |
| `DBS_SSH_TARGETS` · `DBS_SCHEDULE_PUSH_TARGET` | Named SFTP targets, and the default one to push to |
| `DBS_EXCLUDE_MODELS` | Models to skip, in addition to the defaults. `-label` re-includes one |
| `DBS_FILE_ROOTS` · `DBS_RESTORE_ROOTS` | Extra directories to embed; directories a restore may write into |
| `DBS_PASSPHRASE` | An explicit passphrase, overriding the derived one |
| `DBS_KDF_TIME_COST` · `DBS_KDF_MEMORY_COST` · `DBS_KDF_PARALLELISM` | Argon2id cost for new backups |
| `DBS_SETUP_WIZARD` | Send superusers to the guard wizard until it is configured. Default `True` |
| `DBS_ADMIN_CONSOLE_SHELL` | Allow free-form SSH commands from the console. Default `False` |
| `DBS_ANOMALY_ENFORCE` · `DBS_TRUSTED_NETWORKS` · `DBS_GEOLOCATION` | Guard enforcement, trusted CIDRs, browser location |
| `DBS_ANOMALY_DETECTOR` · `DBS_ANOMALY_MIN_ROWS` | A replacement detector class; events before a per-account model is fitted |
| `DBS_GUARD_POLL_SECONDS` · `DBS_GUARD_EVERYWHERE` | How often an open page re-checks; whether the poller covers the whole admin |
| `DBS_SECURITY_RETENTION_DAYS` | Telemetry retention for `dbs security purge` (default 90) |
| `DBS_MAX_UPLOAD_BYTES` · `DBS_MAX_PAYLOAD_BYTES` | Restore upload cap (1 GiB); decompressed payload cap (4 GiB) |
| `DBS_TRUST_FORWARDED_FOR` · `DBS_TRUSTED_PROXIES` | Read the client address from `X-Forwarded-For`, behind that many proxies |

The manager reads its own environment variables:

| Variable | Purpose |
|---|---|
| `DBS_MANAGER_HOME` | The data folder |
| `DBS_MANAGER_DATABASE_URL` | `postgres://…` or `mysql://…` instead of the local SQLite file |

---

## Python API

```python
from dbs import create_backup, restore_backup, validate_backup

blob = create_backup("passphrase", output="backup.dbs")
report = validate_backup(blob, "passphrase")   # report.ok, report.summary()
result = restore_backup(blob, "passphrase")    # result.healed if it repaired corruption
```

```python
from dbs.transports import SSHTarget, open_session

with open_session(SSHTarget.from_settings("offsite")) as session:
    session.push("backup.dbs", "backup.dbs")
    for item in session.details():
        print(item.name, item.size, item.modified)
```

A target can carry its credentials and pinned host key in memory
(`SSHTarget(private_key=…, host_key="ssh-ed25519 AAAA…", use_agent=False)`); a server that
presents a different key raises `HostKeyError`.

---

## How it heals

On write, the encrypted stream is split into blocks. Each block gets a BLAKE2b hash and a
layer of Reed-Solomon parity, and the whole stream is stored **twice**, header and manifest
included. On read, each block is taken from whichever copy verifies, and sparse bit-flips
are corrected in place even when *both* copies are hit. Every recovered block is checked
against its stored hash. A freshly written backup is re-read and verified end to end before
the command reports success.

**Recoverable:** whole-block loss in one copy, and sparse byte errors in both copies up to
the parity budget (about 8 bytes per 255-byte codeword by default). **Not recoverable:** a
block destroyed beyond the parity budget in both copies — DBS then refuses to restore and
names the failed blocks.

## Security model

* **Argon2id** derives a key from the passphrase; **AES-256-GCM** encrypts the payload under
  a random data key wrapped by it. The file never holds the passphrase or the raw data key.
* A wrong passphrase fails the GCM tag check; it never yields partial or garbage data.
* SFTP credentials in the panel, and every server credential, passphrase, `.env` version
  and archive in the manager, are sealed with AES-256-GCM under keys derived from the
  installation's secret, and never returned by any page or API.
* SSH host keys are verified by default; the manager pins exactly the key you confirmed.
  Remote commands are built from fixed argument lists, and passphrases travel on standard
  input, never on a command line.

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

**"Set DBS_BACKUP_DIR"** — the schedule, restore from a stored backup and health need it.

**The panel logged me out.** `python manage.py dbs security unlock USERNAME`, then add your
network to the trusted list.

**`/admin/dbs/` gives a 404.** The panel is for superusers only, and needs
`django.contrib.admin` in `INSTALLED_APPS` alongside `dbs`.

**A restore raises `RestoreError` about a path.** Add the directory to `DBS_RESTORE_ROOTS`.

**`django_dbs run` shows "the interface was not built".** You installed from a source
checkout. Install from PyPI, or build it once with `scripts/build_manager_ui.sh`.

**`django_dbs` is not recognized / command not found.** pip installed the script into a
folder that is not on your `PATH`, common with Windows user installs and
`pip install --user`; pip prints that folder in a warning during the install. Add it to
`PATH`, or run `python -m dbs.manager run` instead. `dbs-client` works the same way as
`python -m dbs.client`.

**The manager cannot reach a server.** Re-run the wizard's *Check* step: it names whether
the SSH login, the host key, the project path or the server's django-dbs version is the
problem.

**The manager says django-dbs is "Not found" on a server that has it.** The manager runs the
Python saved for that server over a non-interactive SSH login, which loads no virtualenv. The
check names the Python it used and the error it got, and offers the Python where django-dbs
is installed; choose *Use this Python*. Or open the server's settings and pick the project
again with *Browse the server*.

---

## Upgrading

```bash
pip install --upgrade django-dbs
python manage.py dbs upgrade
```

It applies pending DBS migrations itself, and prints, with the exact line to add, anything
that means editing your own code. `--check` changes nothing and exits non-zero when
something needs doing, for CI. `--backups DIR` reads old backups and converts any written in
an older format into a new file beside the original. Nothing in DBS ever deletes or
overwrites a backup.

**From 0.4.x:** `dbs upgrade` applies the audit and schedule migrations. If you set
`DBS_SCHEDULE_INTERVAL`, turn the schedule on once in the panel, or keep running
`dbs schedule --interval …` as before. Projects behind uWSGI without threads should set
`DBS_SCHEDULER = "command"`.

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
the SIL OFL 1.1) and the Tajawal typeface (SIL OFL 1.1).
