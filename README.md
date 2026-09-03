# DBS — Django Backup Solution

> 🚧 **Under development.** DBS is in active development and its API may change.
>
> Created by **Sudum Technology — Research and Development sector**.
> Our very tiny contribution to this world.

DBS backs up a Django project into **one encrypted file** — rows, relations and
files together. That file is *redundant* and *self-healing*: it holds **two
copies** of your data plus **Reed-Solomon parity**, so silent corruption is
detected and repaired when you restore, instead of quietly poisoning the data
you were relying on.

You drive it three ways: a command (`manage.py dbs`), a control panel in the
Django admin, and a `dbs-client` command that pulls backups onto your own
machine.

---

## Quick start

**1. Install and enable it.**

```bash
pip install django-dbs
```

```python
# settings.py
INSTALLED_APPS = [
    ...,
    "django.contrib.admin",
    "dbs",
]

MIDDLEWARE = [
    ...,
    "dbs.security.middleware.DBSSecurityMiddleware",
]
```

```bash
python manage.py migrate
```

**2. Take a backup.**

```bash
python manage.py dbs backup backup.dbs
```

That's it. No passphrase to invent — DBS derives one from your `SECRET_KEY`.

**3. Check it.**

```bash
python manage.py dbs validate backup.dbs --passphrase
```

**4. Rehearse a restore** (changes nothing):

```bash
python manage.py dbs restore backup.dbs --dry-run
```

Then open `/admin/dbs/` as a superuser for the control panel.

> **One thing to write down.** Your backups are encrypted with a key derived
> from `SECRET_KEY`. If you ever change `SECRET_KEY` without keeping the old
> value in `SECRET_KEY_FALLBACKS`, **older backups can no longer be opened**.
> Run `python manage.py dbs key --show` and store the result somewhere safe.

---

## What you get

* **One encrypted file** per backup — rows, relations and files.
* **Two copies plus Reed-Solomon parity** inside it, so bit-rot is repaired on
  restore rather than inherited.
* **Nothing to configure**: the encryption key comes from `SECRET_KEY`.
* **A control panel** at `/admin/dbs/`, mounted automatically, in the admin's
  own theme.
* **A session guard** on that panel: superusers only, every request scored, and
  a shell command that always lets you back in.
* **Scheduled backups** with retention, and **off-site copies** over SFTP.
* **`dbs-client`** to pull backups onto your laptop over SSH.
* **Instructions for AI coding assistants**, shipped inside the package.

---

## The control panel

Once `dbs` is installed alongside `django.contrib.admin` and you have run
`migrate`, the panel is at **`/admin/dbs/`**. There is no `urls.py` change to
make.

| Page | What it does |
|---|---|
| Dashboard | Recent backups, your SFTP targets, current guard state |
| Take a backup | Download it, or push it straight to a target |
| Restore | Upload a `.dbs` file — with a dry run that changes nothing |
| SFTP targets | Add and edit servers; credentials are encrypted at rest |
| Console | Per target: check the connection, list backups, run one on the server |
| Wiki | Passphrases, restore semantics, the guard, troubleshooting |

**Superusers only.** There is deliberately no grantable permission for it: the
panel can download and overwrite your entire database.

On your first visit a short wizard asks which networks you log in from and how
strict the guard should be. You can change all of it later from the panel.

The older `include("dbs.contrib.urls")` pages still work unchanged.

---

## Backups on a schedule

```bash
python manage.py dbs schedule --interval 6h --output-dir /var/backups/myproject --keep 14
```

| Flag | Meaning |
|---|---|
| `--interval` | How often: `90s`, `30m`, `6h`, `1d`. Default `DBS_SCHEDULE_INTERVAL`, else 24h |
| `--output-dir` | Where backups land. Default `DBS_BACKUP_DIR` |
| `--prefix` | Filename prefix, so several projects can share a directory |
| `--keep` | How many local backups to retain |
| `--push` | Name of a `DBS_SSH_TARGETS` entry to upload to as well |
| `--keep-remote` | How many uploaded backups to retain |
| `--once` | Run one cycle and exit — use this from cron, or to test |

Backups are named `prefix-YYYYMMDD-HHMMSSZ.dbs` in UTC, so sorting by name
sorts by time. Retention only ever considers files matching that pattern and
prefix; anything else in the directory is left alone.

Run **one scheduler per output directory** — two loops sharing a directory race
on retention. A failing cycle is logged and the schedule carries on.

<details>
<summary>Running it under systemd</summary>

```ini
[Unit]
Description=DBS scheduled backups
After=network-online.target

[Service]
User=deploy
WorkingDirectory=/srv/myproject
ExecStart=/srv/myproject/.venv/bin/python manage.py dbs schedule --interval 6h \
          --output-dir /var/backups/myproject --keep 14
Restart=always

[Install]
WantedBy=multi-user.target
```

`SIGTERM` stops the loop immediately rather than after the current interval, so
`systemctl restart` and container shutdowns are prompt.

For cron, use `--once` for a single cycle. In Docker, run the loop as the
container's main process.
</details>

---

## Off-site copies over SFTP

Two ways to define a server. **In settings**, for automation:

```python
# settings.py — reference a key by path; no secrets in the file
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

**Or in the admin**, under *SFTP targets*, where passwords and private keys are
encrypted at rest under a key derived from `SECRET_KEY` and never shown again
once saved.

Then push on every scheduled cycle:

```bash
python manage.py dbs schedule --interval 6h --output-dir /var/backups \
    --push offsite --keep-remote 7
```

Host keys are verified and unknown hosts are **rejected by default**. Point
`known_hosts` at a file, or set `auto_add_host_key` to trust whatever key the
server presents on first contact — which gives up detection of a
machine-in-the-middle on that first connection.

Needs `pip install "django-dbs[ssh]"`.

---

## Restoring

```bash
python manage.py dbs restore backup.dbs --dry-run   # rehearse, change nothing
python manage.py dbs restore backup.dbs             # merge into what's there
python manage.py dbs restore backup.dbs --flush     # replace instead of merge
```

**Start with `--dry-run`.** It performs the real load inside a transaction it
rolls back, and writes no files, so you see exactly what would happen.

Things worth knowing before you restore for real:

* **It merges by default.** Rows created after the backup was taken are not
  deleted. `--flush` clears the backed-up models first — children before
  parents, in the same transaction — so the restore replaces instead.
* **The load is one transaction.** If anything fails midway the database is left
  untouched.
* **File writes are confined** to directories listed in `DBS_RESTORE_ROOTS` (or
  `DBS_FILE_ROOTS` if that is unset). Anything outside raises `RestoreError`.
  Set this before restoring backups that embed external files.
* **Migration drift is reported.** A backup records the applied migration per
  app; restoring onto a target that has moved on warns and names the apps.
  Fields and models the target does not know are discarded as rows load.
* **Sequences are reset** after rows carrying explicit primary keys, so the next
  row your project creates does not collide with a restored one.

### Signals during a restore

Rows are saved the way `loaddata` does, with `raw=True`. A `post_save` receiver
that re-runs business side effects must return early on raw saves, or a restore
replays them against a half-loaded database:

```python
@receiver(post_save, sender=Order)
def on_order_saved(sender, instance, created, **kwargs):
    if kwargs.get("raw"):
        return
    ...
```

---

## Pulling backups to your own machine

`dbs-client` connects to a server running DBS, asks it for a fresh backup, and
downloads the file — over one encrypted SSH connection.

```bash
pip install "django-dbs[client]"
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

Downloads stream to a `.part` file and are renamed only once complete, so an
interrupted transfer can never be mistaken for a good backup.

`dbs-client` never restores into a server's database. Use `push` to place a file
there, then run the restore on the server deliberately.

<details>
<summary>Config keys and SSH authentication</summary>

Anything under `[defaults]` applies to every server unless that server overrides
it. Pick a server with `--server NAME`.

| Key | Meaning |
|---|---|
| `host` · `username` · `port` | Where to connect. `host` and `username` required |
| `key_filename` | `.pem` or OpenSSH private key. `~` is expanded |
| `key_passphrase` · `key_passphrase_env` | For an encrypted key file |
| `password` · `password_env` | Password authentication |
| `use_agent` | Use ssh-agent (default `true`) |
| `known_hosts` · `auto_add_host_key` | Host key verification |
| `connect_timeout` | Seconds to wait for the SSH handshake |
| `remote_dir` | Where backups live on the server. Created if missing |
| `project_dir` · `python` · `manage` · `django_settings_module` | How to run `manage.py` remotely |
| `env` | Extra environment variables for the remote command |
| `passphrase` · `passphrase_env` | The backup encryption passphrase |
| `passphrase_transport` | `stdin` (default) or `env` |
| `database` | Database alias to back up |
| `dest` · `prefix` · `keep` · `keep_remote` · `interval` | Local defaults |
| `exec_timeout` | Seconds to allow the remote backup to run |

Any secret can be read from an environment variable instead of the file by
adding `_env` to the key name.

An unrecognised key is an error, not a warning — a typo like `known_host` would
otherwise silently disable host key checking. A config holding a literal secret
and readable by other users is refused, as is one writable by other users.

**The passphrase never appears in a command line**, locally or on the server,
because process arguments are readable by every user via `/proc`. By default the
client runs the remote backup with `--passphrase-stdin` and writes the
passphrase down the SSH channel, so it is in neither the remote process's
arguments nor its environment.

The client invokes `manage.py dbs_backup` on the server, which is the original
command name and still fully supported.
</details>

---

## Choosing what to back up

By default DBS finds every model, treats `FileField`/`ImageField` as files, and
preserves relations. Register a model only to override that, in a `dbs.py` inside
your app (auto-discovered like `admin.py`):

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

`FieldType` values: `VALUE` (default), `FILE`, `FILE_PATH`, `EXCLUDE`.

`DBS_EXCLUDE_MODELS` skips models **in addition** to the built-in exclusions
(content types, permissions, admin log, sessions, and DBS's own tables). Prefix
a label with `-` to back up one the defaults skip:

```python
DBS_EXCLUDE_MODELS = ["myapp.AuditRow", "-sessions.Session"]
```

---

## Passphrases

DBS derives the backup passphrase from `SECRET_KEY`, so a new project needs no
setup. The derivation is domain separated, meaning the backup key is never the
same bytes Django uses for sessions, CSRF and password-reset tokens.

Order of precedence:

1. `--passphrase` or `--passphrase-stdin` on the command line
2. The `DBS_PASSPHRASE` environment variable
3. The `DBS_PASSPHRASE` setting
4. Derived from `SECRET_KEY`

```bash
python manage.py dbs key --show    # print it, and archive it somewhere safe
```

**Rotating `SECRET_KEY`:** keep the old value in `SECRET_KEY_FALLBACKS`. DBS
tries every fallback when restoring and when reading stored SFTP credentials. A
backup encrypted under a key you lost, and did not keep as a fallback, cannot be
opened by anyone.

To keep the passphrase out of the process's command line:

```bash
printf '%s\n' "$SECRET" | python manage.py dbs backup backup.dbs --passphrase-stdin
```

---

## The session guard

The panel can export and overwrite your whole database, so every admin request
from a superuser is scored, and a high enough score ends that account's
sessions.

What feeds the score: time of day, request rate, how risky the attempted action
is, session age, recent failed logins, and whether the network prefix and
browser are ones the account has used before. Scoring uses an
`IsolationForest` — shipped pre-trained on a synthetic corpus so it works from
the first request, then refitted on the account's own history once there is
enough of it.

**If it locks you out, a shell always wins:**

```bash
python manage.py dbs security unlock alice
```

Other subcommands: `status`, `policy`, `retrain`, `reset-baseline USER`,
`events`, `purge`.

Ways to loosen it:

| | |
|---|---|
| `DBS_TRUSTED_NETWORKS` | CIDRs that are scored and recorded but never enforced against |
| `DBS_ANOMALY_ENFORCE = False` | Turn enforcement off entirely |
| Setup wizard | Pick Relaxed instead of Balanced, Strict or Paranoid |
| Learning period | New installs record without enforcing for the first sessions |

**Optional browser location.** `DBS_GEOLOCATION = True` adds distance from a
known location and impossible-travel detection. It is opt-in, stored rounded to
about a kilometre, and can only ever *raise* a risk score, never lower one —
it comes from the browser and can be forged. Declining the permission prompt
changes nothing else.

**Remote command execution is off by default.** `DBS_ADMIN_CONSOLE_SHELL = True`
adds a free-form command box to the target console, which gives any superuser
arbitrary command execution on that server from a browser. The named actions —
check connection, list backups, create the remote directory — always work
without it.

---

## Working with AI assistants

DBS ships instructions that teach a coding assistant how to use it correctly:
the settings, the commands, the restore semantics, and the mistakes that lose
data.

```bash
python manage.py dbs ai            # writes .claude/skills/django-dbs/
python manage.py dbs ai --agents   # also appends a section to AGENTS.md
python manage.py dbs ai --check    # CI: fail if the installed copy has drifted
```

The source of truth lives inside the installed package under `dbs/ai/`, so it
always matches the version you actually have.

---

## Command reference

```bash
python manage.py dbs                    # overview of everything below
python manage.py dbs backup OUTPUT
python manage.py dbs restore INPUT      [--dry-run] [--flush] [--no-data] [--no-files]
python manage.py dbs validate INPUT     [--passphrase]
python manage.py dbs schedule           [--interval 6h] [--output-dir DIR] [--once]
python manage.py dbs key                [--show]
python manage.py dbs security ACTION    [USERNAME]
python manage.py dbs ai                 [--agents] [--check] [--print]
python manage.py dbs upgrade            [--check] [--self] [--backups DIR] [--offline]
```

Every command takes `--passphrase`, `--passphrase-stdin` and `--database` where
they make sense. `backup` also takes `--no-compress`, `--no-verify`,
`--block-size`, `--kdf-time` and `--kdf-memory`.

`python manage.py django-dbs` runs the same command under its older name. The
original `dbs_backup`, `dbs_restore`, `dbs_validate` and `dbs_schedule` commands
still work exactly as before and are **not** deprecated.

---

## Settings reference

Everything is optional. DBS works with none of these set.

### What to back up

| Setting | Purpose |
|---|---|
| `DBS_EXCLUDE_MODELS` | Models to skip, in addition to the defaults. `-label` re-includes one |
| `DBS_FILE_ROOTS` | Extra directories embedded in every backup |
| `DBS_RESTORE_ROOTS` | Directories a restore may write into (falls back to `DBS_FILE_ROOTS`) |

### Where backups go

| Setting | Purpose |
|---|---|
| `DBS_BACKUP_DIR` | Default output directory for `dbs schedule` |
| `DBS_BACKUP_PREFIX` | Default filename prefix |
| `DBS_SCHEDULE_INTERVAL` | Default interval (default `24h`) |
| `DBS_SCHEDULE_KEEP` | Default local retention count (default 7) |
| `DBS_SSH_TARGETS` | Named SFTP connection profiles |
| `DBS_SCHEDULE_PUSH_TARGET` | Default target to push to |
| `DBS_SCHEDULE_KEEP_REMOTE` | Default retention for pushed backups |

### Encryption

| Setting | Purpose |
|---|---|
| `DBS_PASSPHRASE` | Explicit passphrase, overriding the one derived from `SECRET_KEY` |
| `DBS_KDF_TIME_COST` · `DBS_KDF_MEMORY_COST` · `DBS_KDF_PARALLELISM` | Argon2id cost for new backups |

### The panel and its guard

| Setting | Purpose |
|---|---|
| `DBS_SETUP_WIZARD` | Redirect superusers to the wizard until configured. Default `True` |
| `DBS_ADMIN_CONSOLE_SHELL` | Allow free-form SSH commands from the console. Default `False` |
| `DBS_ANOMALY_ENFORCE` | Whether a blocking verdict ends sessions. Default `True` |
| `DBS_TRUSTED_NETWORKS` | CIDRs scored but never enforced against |
| `DBS_ANOMALY_DETECTOR` | Dotted path to a replacement detector class |
| `DBS_ANOMALY_MIN_ROWS` | Events before a per-account model is fitted (default 50) |
| `DBS_GUARD_POLL_SECONDS` | How often an open page re-checks authorization (default 15) |
| `DBS_GUARD_EVERYWHERE` | Extend the guard poller to the whole admin. Default `False` |
| `DBS_GEOLOCATION` | Collect browser location as a signal. Default `False` |
| `DBS_SECURITY_RETENTION_DAYS` | Telemetry retention for `dbs security purge` (default 90) |
| `DBS_MAX_UPLOAD_BYTES` | Restore upload cap (default 1 GiB) |
| `DBS_MAX_PAYLOAD_BYTES` | Decompressed payload cap on restore (default 4 GiB) |
| `DBS_TRUST_FORWARDED_FOR` | Read the client IP from `X-Forwarded-For`. Default `False` |
| `DBS_TRUSTED_PROXIES` | Proxies in front, counted from the right of that header (default 1) |

Only enable `DBS_TRUST_FORWARDED_FOR` behind a proxy you control, and set
`DBS_TRUSTED_PROXIES` to the number of hops — otherwise the client address is
whatever the caller claims.

---

## Python API

```python
from dbs import create_backup, restore_backup, validate_backup

blob = create_backup("passphrase", output="backup.dbs")
report = validate_backup(blob, "passphrase")   # report.ok, report.summary()
result = restore_backup(blob, "passphrase")    # result.healed if it repaired corruption
```

```python
from dbs import default_passphrase          # the one derived from SECRET_KEY
from dbs.transports import SSHTarget, open_session

with open_session(SSHTarget.from_settings("offsite")) as session:
    session.push("backup.dbs", "backup.dbs")
    for item in session.details():
        print(item.name, item.size, item.modified)
```

`open_session` reuses one connection for a whole cycle. The module-level
`push_backup`, `pull_backup`, `pull_backup_to`, `list_backups`,
`list_backup_details`, `delete_backup` and `check_connection` helpers open and
close a connection each.

---

## How it heals

On write, the encrypted stream is split into blocks. Each block gets a BLAKE2b
hash and a layer of Reed-Solomon parity, and the whole stream is stored **twice**
— header and manifest included. On read, each block is taken from whichever copy
verifies, and sparse bit-flips are corrected in place even when *both* copies are
hit. Every recovered block is checked against its stored hash, so a
mis-correction cannot slip through. A freshly written backup is re-read and
verified end-to-end before the command reports success.

**Recoverable:** whole-block loss in one copy, and sparse byte errors in both
copies up to the parity budget (~8 bytes per 255-byte codeword by default).

**Not recoverable:** a block destroyed beyond the parity budget in *both* copies.
DBS then refuses to restore and names the failed blocks, rather than handing you
silently wrong data.

## Security model

* **Argon2id** derives a key from the passphrase. Raise `KDFParams` cost for more
  resistance.
* **Envelope encryption**: a random data key encrypts the payload with
  **AES-256-GCM**, and that data key is wrapped by the passphrase-derived key.
  The file stores the salt, the Argon2 parameters and the wrapped key — never
  the passphrase, never the raw data key.
* A wrong passphrase fails the GCM tag check and is reported as such. It can
  never produce partial or garbage data.
* Stored SFTP credentials are encrypted at rest with AES-256-GCM under a
  separately derived `SECRET_KEY` key, and are never displayed again.
* Transfers run over SSH/SFTP with host key verification on by default.

See [SECURITY.md](SECURITY.md) for the reporting process and the threat model.

## Observability

DBS logs to the `dbs` logger: backup and restore start and finish, skipped
files, SFTP transfers, scheduled cycles and retention, and — most importantly —
a `WARNING` whenever silent corruption was detected and healed. Route that
logger somewhere you will see it, so a degrading disk is noticed before both
copies are damaged.

```python
LOGGING = {
    "version": 1,
    "loggers": {"dbs": {"handlers": ["console"], "level": "INFO"}},
}
```

`dbs-client --verbose` prints the same log to stderr.

---

## Troubleshooting

**"Credential cannot be read with the current SECRET_KEY"**
The stored SFTP credential was encrypted under a different key. Add the old key
to `SECRET_KEY_FALLBACKS`, or re-enter the credential in the admin.

**The panel logged me out**
The guard scored the request above your logout threshold. Run
`python manage.py dbs security unlock USERNAME`, then add your network to the
trusted list in the setup wizard.

**A restore merged when I wanted it to replace**
Use `--flush`, or tick *Replace instead of merge* in the panel.

**The scheduler will not start**
It needs somewhere to write: pass `--output-dir` or set `DBS_BACKUP_DIR`.

**`/admin/dbs/` gives a 404**
The panel is superusers only, and needs `django.contrib.admin` in
`INSTALLED_APPS` alongside `dbs`.

**A restore raises `RestoreError` about a path**
File restores are confined to `DBS_RESTORE_ROOTS` (or `DBS_FILE_ROOTS`). Add the
directory the backup wants to write into.

---

## Upgrading

One command tells you what this project still needs, and does the parts that are safe to
do automatically:

```bash
python manage.py dbs upgrade
```

```
DBS 0.3.1
[ok]     installed app      dbs is in INSTALLED_APPS
[done]   migrations         applied the pending dbs migrations
[ok]     dependencies       scikit-learn is available
[warn]   session guard      the control panel is reachable but nothing is scoring requests
                            MIDDLEWARE = [..., "dbs.security.middleware.DBSSecurityMiddleware"]
```

It applies pending DBS migrations and refreshes the shipped AI instructions itself. Anything
that means editing your own code it prints, with the exact line and where it goes — it never
rewrites your settings.

| | |
|---|---|
| `--check` | Report only, change nothing. Exits non-zero if something needs doing — use this in CI |
| `--self` | Install a newer django-dbs from PyPI if one exists. Refuses on a source checkout |
| `--backups DIR` | Also read the backups in `DIR` and convert any written in an older format |
| `--offline` | Do not contact PyPI |

`python manage.py dbs-upgrade` and `python manage.py dbs_upgrade` are the same command.

### What it checks

Installed app, pending migrations, `scikit-learn`, whether the panel is mounted, whether the
guard middleware is active, `DBS_EXCLUDE_MODELS` written for pre-0.2.2 semantics, whether a
passphrase can be derived, whether `DBS_RESTORE_ROOTS` would refuse every path, and whether
the installed AI instructions match the version you have.

### Old backups

```bash
python manage.py dbs upgrade --backups /var/backups/myproject
```

Every backup ever written by any released DBS is at container format version 1, which this
version reads, so today this reports "nothing to convert". It exists because a future format
change would otherwise strand files that already exist.

When a backup *can't* be read forward, the command **stops and changes nothing**:

- It never deletes, moves or overwrites a backup — not with a flag, not with confirmation.
  Conversion writes a new `.converted` file beside the original and leaves the original
  alone.
- A converted file is validated end to end before it counts as converted.
- It tells you the safe option first: install the version that wrote the file in a separate
  environment and restore from there. You rarely need to give anything up.

Only if you genuinely no longer need those files can you continue, and doing so is
deliberately hard to automate: there is no flag, it requires a terminal, and it requires
typing an exact phrase naming how many backups you are giving up. Even then nothing is
deleted — the files stay on disk.

### From 0.2.x

1. `pip install --upgrade django-dbs`
2. `python manage.py dbs upgrade`

That applies the migrations 0.3.0 added and tells you about anything else. `scikit-learn`
arrives automatically as a dependency. Your existing backups restore unchanged, and the
`dbs_backup` / `dbs_restore` / `dbs_validate` / `dbs_schedule` commands keep working.

## Development

```bash
pip install -e ".[dev]"
pytest
```

Set `DBS_TEST_HOUR=3` to run the suite as though it were 03:00 UTC — the session
guard scores time of day, so this makes that behaviour reproducible.

## License

MIT
