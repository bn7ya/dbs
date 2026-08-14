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
* **Scheduled backups** on the server, with retention.
* **A `dbs-client` command** that pulls backups off your server over SSH.
* CLI · admin-UI download · SFTP.

## Install

```bash
pip install django-dbs              # on the server: the library + management commands
pip install "django-dbs[client]"    # on your machine: the dbs-client command
```

Add the app on the server:

```python
INSTALLED_APPS = [..., "dbs"]
```

The `[client]` extra adds `paramiko` (SSH/SFTP) and, on Python 3.9/3.10, a TOML
parser. `[ssh]` remains available as the server-side SFTP extra.

> The `[client]` extra still installs Django, because DBS depends on it. You do
> not need a Django project on the machine running `dbs-client` — the client
> never reads Django settings.

---

# On the server

## 1. (Optional) declare what to back up

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

## 2. Back up / restore / validate from the CLI

```bash
python manage.py dbs_backup   backup.dbs            # prompts for a passphrase
python manage.py dbs_validate backup.dbs            # structural check, no passphrase
python manage.py dbs_validate backup.dbs --passphrase secret  # + verify decryption
python manage.py dbs_restore  backup.dbs            # restore rows + files
python manage.py dbs_restore  backup.dbs --dry-run  # rehearse, change nothing
python manage.py dbs_restore  backup.dbs --flush    # replace instead of merge
```

The passphrase comes from `--passphrase`, then `$DBS_PASSPHRASE`, then a prompt.
`--passphrase-stdin` reads it from the first line of standard input instead,
which keeps it out of the process's command line:

```bash
printf '%s\n' "$SECRET" | python manage.py dbs_backup backup.dbs --passphrase-stdin
```

### Signals during restore

`dbs_restore` saves each row the same way `loaddata` does: with `raw=True`.
A `pre_save`/`post_save` receiver that re-runs business side effects — awarding
points, sending notifications, recomputing derived state — must return early on
raw saves, or a restore replays those effects against a half-loaded database:

```python
@receiver(post_save, sender=Order)
def on_order_saved(sender, instance, created, **kwargs):
    if kwargs.get("raw"):
        return
    ...
```

## 3. Automatic backups on a schedule

`dbs_schedule` runs backups on a repeating interval, prunes old ones, and can
push each backup to another host in the same cycle.

```bash
export DBS_PASSPHRASE='…'
python manage.py dbs_schedule --interval 6h --output-dir /var/backups/myproject --keep 14
```

| Flag | Meaning |
|---|---|
| `--interval` | How often to run: `90s`, `30m`, `6h`, `1d`. Defaults to `DBS_SCHEDULE_INTERVAL`, else 24h. |
| `--output-dir` | Where backups are written. Defaults to `DBS_BACKUP_DIR`. |
| `--prefix` | Filename prefix, so several projects can share a directory. |
| `--keep` | How many local backups to retain. |
| `--push` | Name of a `DBS_SSH_TARGETS` entry to also upload to. |
| `--keep-remote` | How many pushed backups to retain. |
| `--once` | Run one cycle and exit — use this from cron, or to test the setup. |
| `--database` `--no-compress` `--no-verify` `--block-size` `--kdf-time` `--kdf-memory` | As for `dbs_backup`. |

It reads the passphrase from `$DBS_PASSPHRASE` and **never prompts**; if the
variable is missing it exits immediately with an explanation rather than hanging
on an invisible prompt. A cycle that fails is logged and the schedule continues.

Backups are named `prefix-YYYYMMDD-HHMMSSZ.dbs` in UTC, so sorting by name is
sorting by time. Retention only ever considers files matching that convention
and the configured prefix — anything else in the directory is left alone, and
`--keep` must be at least 1.

**systemd:**

```ini
[Unit]
Description=DBS scheduled backups
After=network-online.target

[Service]
User=deploy
WorkingDirectory=/srv/myproject
Environment=DBS_PASSPHRASE=…
ExecStart=/srv/myproject/.venv/bin/python manage.py dbs_schedule --interval 6h \
          --output-dir /var/backups/myproject --keep 14
Restart=always

[Install]
WantedBy=multi-user.target
```

`SIGTERM` stops the loop straight away rather than after the current interval,
so `systemctl restart` and container shutdowns are immediate. Run **one
scheduler per output directory** — two loops sharing a directory will race on
retention. Prefer `Environment=` in a `chmod 600` unit file, or a systemd
credential, over a passphrase in a shell profile.

**cron / Docker:** use `--once` from cron for a single cycle, or run the loop as
the container's main process.

## 4. Download / upload from the admin UI

```python
# urls.py
urlpatterns += [path("dbs/", include("dbs.contrib.urls"))]
```

Superusers can then visit `/dbs/backup/` to download an encrypted backup and
`/dbs/restore/` to upload one. The passphrase is entered in the form and never
stored server-side.

## 5. Ship a backup to another server (SFTP)

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

---

# On your machine: `dbs-client`

`dbs-client` connects to a server where django-dbs is installed, asks it to make
a fresh backup, and downloads the file — all over one encrypted SSH connection.
It can also list, pull, push, prune, and run on a schedule of its own.

```bash
pip install "django-dbs[client]"
dbs-client init                 # writes dbs-client.toml, mode 600
$EDITOR dbs-client.toml
dbs-client test-connection
dbs-client backup
```

## Configuration

`dbs-client` reads the first config it finds: `--config PATH`, then
`$DBS_CLIENT_CONFIG`, then `./dbs-client.toml`, then `~/.config/dbs/client.toml`.
`dbs-client init --print` writes an annotated template to standard output.

```toml
[defaults]
server = "production"
dest = "~/dbs-backups"
keep = 14
keep_remote = 7
interval = "6h"

[servers.production]
host = "app.example.com"
username = "deploy"
port = 22
key_filename = "~/.ssh/production.pem"
known_hosts = "~/.ssh/known_hosts"

project_dir = "/srv/myproject"
python = "/srv/myproject/.venv/bin/python"
manage = "manage.py"
django_settings_module = "myproject.settings.production"
remote_dir = "/var/backups/myproject"

passphrase_env = "DBS_PASSPHRASE"
prefix = "production"
keep = 30
```

Anything under `[defaults]` applies to every server unless that server overrides
it. Pick a server with `--server NAME`, before or after the subcommand.

| Key | Meaning |
|---|---|
| `host` · `username` · `port` | Where to connect. Required: `host`, `username`. |
| `key_filename` | `.pem` or OpenSSH private key. `~` is expanded. |
| `key_passphrase` · `key_passphrase_env` | For an encrypted key file. |
| `password` · `password_env` | Password authentication. |
| `use_agent` | Use ssh-agent (default `true`). |
| `known_hosts` · `auto_add_host_key` | Host key verification; see below. |
| `connect_timeout` | Seconds to wait for the SSH handshake. |
| `remote_dir` | Where backups live on the server. Created if missing. |
| `project_dir` · `python` · `manage` · `django_settings_module` | How to run `manage.py` on the server. |
| `env` | Extra environment variables for the remote command. |
| `passphrase` · `passphrase_env` | The **backup encryption** passphrase. |
| `passphrase_transport` | `stdin` (default) or `env`; see below. |
| `database` | Database alias to back up. |
| `dest` · `prefix` · `keep` · `keep_remote` · `interval` | Local defaults for this server. |
| `exec_timeout` | Seconds to allow the remote backup to run. |

A key that isn't recognised is an error, not a warning — a typo like
`known_host` would otherwise silently disable host key checking.

If the file holds a literal `password`, `passphrase` or `key_passphrase` and is
readable by other users, `dbs-client` refuses to run and tells you to
`chmod 600` it. A config writable by other users is refused regardless, because
it decides which command runs on your server.

## Commands

| Command | What it does |
|---|---|
| `init` | Write a starter config (mode 600, never overwrites). `--print` dumps it to stdout. |
| `test-connection` | Check auth, host key policy, remote directory, the server's DBS version, and that `manage.py dbs_backup` runs. |
| `list` | List remote backups with size and time. `--json`, `--all`, `--prefix`. |
| `backup` | Make a backup on the server and download it. |
| `pull NAME` / `pull --latest` | Download a backup that already exists. |
| `push PATH` | Upload a local backup file to the server. |
| `prune` | Apply retention locally, remotely, or both. `--dry-run` shows what would go. |
| `schedule` | Repeat `backup` on an interval. `--once` runs a single cycle. |
| `validate PATH` | Check a local backup file. `--structure-only` skips decryption. |

```bash
dbs-client test-connection
# [ok] ssh authentication      deploy@app.example.com:22
# [ok] host key policy         reject-unknown
# [ok] remote shell            Linux 6.1.0
# [ok] remote directory        /var/backups/myproject
# [ok] django-dbs on server    0.2.0
# [ok] manage.py dbs_backup    ready
# [ok] backups present         7

dbs-client backup --keep 14 --keep-remote 7
dbs-client pull --latest
dbs-client prune --keep 7 --local-only --dry-run
dbs-client schedule --interval 6h --keep 30
```

`backup` triggers `manage.py dbs_backup` on the server, downloads the result to
`dest`, validates it locally, then applies retention. `--no-fetch` leaves it on
the server, `--delete-remote` removes the remote copy once it is safely
downloaded, and `--no-validate` skips the local check. Downloads stream to a
`.part` file and are renamed into place only once complete, so an interrupted
transfer can never be mistaken for a good backup.

`schedule` uses the same loop as the server-side command: `SIGTERM` and `Ctrl-C`
stop it promptly, and a failing cycle is logged without ending the schedule. It
resolves the passphrase once at start-up and never prompts.

`validate` needs no Django project and no settings — it works anywhere the file
is.

## SSH authentication

| Method | Configure |
|---|---|
| `.pem` or OpenSSH key | `key_filename = "~/.ssh/production.pem"` |
| Encrypted key file | the above plus `key_passphrase_env = "…"` (or `key_passphrase`) |
| Password | `password_env = "…"` (or `password`) |
| ssh-agent | name neither a key nor a password; `use_agent` defaults to `true` |

Any secret can be given directly or read from an environment variable by adding
`_env` to the key name, which keeps it out of the file entirely.

Host keys are verified and **unknown hosts are rejected by default**. Point
`known_hosts` at a file (`~/.ssh/known_hosts` is typical) or leave it unset to
use the system host keys. `auto_add_host_key = true` trusts whatever key the
server presents on first contact — `test-connection` always prints which policy
is in effect so this doesn't get left on by accident.

## Passphrases in unattended runs

The backup passphrase never appears in a command line — not locally, and not on
the server. There is no `--passphrase` flag on `dbs-client` at all, because
process arguments are readable by every user on the machine via `/proc`.

* **`passphrase_transport = "stdin"` (default, needs django-dbs ≥ 0.2.0 on the
  server).** The client runs `manage.py dbs_backup --passphrase-stdin` and writes
  the passphrase down the encrypted SSH channel's standard input. It is in
  neither the remote process's arguments nor its environment, and never touches
  the server's disk.
* **`passphrase_transport = "env"` (for servers still on 0.1.x).** The passphrase
  is still sent over stdin, but a shell reads it into `DBS_PASSPHRASE` for the
  backup process. It is then visible in that process's environment to root and
  to the same user — the same exposure as a systemd `Environment=` line, and
  better than a command-line argument.

Locally the passphrase is resolved from `passphrase_env`, then a literal
`passphrase`, then `$DBS_PASSPHRASE`, then an interactive prompt.

---

## Python API

```python
from dbs import create_backup, restore_backup, validate_backup

blob = create_backup("passphrase", output="backup.dbs")
report = validate_backup(blob, "passphrase")   # report.ok / report.summary()
result = restore_backup(blob, "passphrase")    # result.healed is True if it repaired corruption
```

```python
from dbs.transports import SSHTarget, open_session

with open_session(SSHTarget.from_settings("offsite")) as session:
    session.push("backup.dbs", "backup.dbs")
    for item in session.details():
        print(item.name, item.size, item.modified)
    session.delete("old-backup.dbs")
```

`open_session` reuses one connection for a whole trigger-fetch-prune cycle. The
module-level `push_backup`, `pull_backup`, `pull_backup_to`, `list_backups`,
`list_backup_details`, `delete_backup` and `check_connection` helpers open and
close a connection each.

```python
from dbs.client import load_client_config, resolve_client_passphrase, backup_and_fetch

profile = load_client_config().server("production")
result = backup_and_fetch(profile, resolve_client_passphrase(profile), keep=14)
print(result.local_path, result.size)
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
* Transfers run over SSH/SFTP with host key verification on by default.
* Passphrases are never passed as command-line arguments; see *Passphrases in
  unattended runs* above.

## Restore semantics

* The database load runs in a **single transaction**: if anything fails midway,
  every row is rolled back and the database is left untouched.
* Backup collection also runs in a transaction. Where the connection's isolation
  level is READ COMMITTED, every statement takes its own snapshot, so a backup
  that spans many models while the application keeps writing can read some of
  them before a concurrent change and others after it. Set the connection to
  REPEATABLE READ, or back up during a quiet window, when consistency across
  models matters.
* Writing a `.dbs` file is **atomic and durable** (temp file + fsync + rename),
  and verify-after-write re-reads the bytes that actually landed on disk. Uploads
  and downloads land the same way, via a `.part` file that is renamed on success.
* File restores are **confined**: `FILE_PATH` and file-root entries are only
  written when the target resolves under a directory listed in
  `DBS_RESTORE_ROOTS` (or, if unset, `DBS_FILE_ROOTS`). Anything else raises
  `RestoreError`. Configure the allow-list before restoring backups that embed
  external files.
* Restoring merges by primary key into the target database; rows created after
  the backup was taken are not deleted. When the target already holds rows for
  the backed-up models, the restore says so in a warning. `--flush` clears those
  models first so the restore replaces instead, and `--dry-run` rehearses the
  whole load in a transaction it rolls back.
* Rows carrying explicit primary keys leave the database sequences reset behind
  them, so the next row the project creates does not collide with a restored one.
* A restore compares the backup's recorded migration state against the target's
  and warns when they have drifted. Fields and models the target does not know
  are discarded as the rows load, so it is worth reading that warning before
  treating the restore as complete.
* `dbs-client` never restores into a server's database. Use `push` to place a
  file there, then run `dbs_restore` on the server deliberately.

## Observability

DBS logs to the `dbs` logger: backup/restore start and finish, skipped source
files, SFTP transfers, scheduled cycles and retention, and — most importantly —
a `WARNING` whenever silent corruption was detected and healed. Route that
logger to your monitoring so a degrading disk is noticed before both copies are
damaged:

```python
LOGGING = {
    "version": 1,
    "loggers": {"dbs": {"handlers": ["console"], "level": "INFO"}},
}
```

`dbs-client --verbose` prints the same log to stderr. Files that could not be
read during a backup are also recorded in the manifest
(`validate_backup(...).stats["skipped_files"]`).

## Settings reference

| Setting | Purpose |
|---|---|
| `DBS_EXCLUDE_MODELS` | `["app.Model", ...]` skipped in addition to the defaults (contenttypes, permissions, admin log, sessions). Prefix a label with `-` (e.g. `"-sessions.Session"`) to back up a model the defaults skip. |
| `DBS_FILE_ROOTS` | Extra directories embedded in every backup. |
| `DBS_RESTORE_ROOTS` | Directories file restores may write into (falls back to `DBS_FILE_ROOTS`). |
| `DBS_SSH_TARGETS` | Named SFTP connection profiles. |
| `DBS_BACKUP_DIR` | Default output directory for `dbs_schedule`. |
| `DBS_BACKUP_PREFIX` | Default backup filename prefix. |
| `DBS_SCHEDULE_INTERVAL` | Default interval for `dbs_schedule` (default `24h`). |
| `DBS_SCHEDULE_KEEP` | Default local retention count (default 7). |
| `DBS_SCHEDULE_PUSH_TARGET` | Default `DBS_SSH_TARGETS` entry to push to. |
| `DBS_SCHEDULE_KEEP_REMOTE` | Default retention count for pushed backups. |
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
