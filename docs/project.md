# DBS in a Django project

DBS runs inside your project. This guide covers what the project needs, the backup commands,
how DBS handles large tables, streaming a backup elsewhere, and choosing what goes into a
backup. For the first steps, see [Getting started](getting-started.md).

## What the project needs

| Requirement | Why |
|---|---|
| A **stable `SECRET_KEY`** | The backup passphrase is derived from it, and a project's backup passphrase must never change. Rotate `SECRET_KEY` only with the old value kept in `SECRET_KEY_FALLBACKS`. |
| **`DBS_BACKUP_DIR`**, writable by the project | Where backups are kept, at most five, and where the panel restores and checks them from. The DBS manager collects its copies from here. |
| `django.contrib.admin`, mounted | The panel lives inside the admin. |
| A superuser | The panel is for superusers only. |
| Python 3.9+ and Django 4.2 to 6.x | |

A `.env` file next to `manage.py`, kept out of version control, is a good home for these:

```ini
# .env
DJANGO_SECRET_KEY=a-long-random-string-that-never-changes
DBS_BACKUP_DIR=/var/backups/myproject
# DBS_PASSPHRASE=only-if-you-want-a-passphrase-other-than-the-derived-one
# DBS_SCHEDULER=thread
```

Read them in `settings.py` with the tool you already use (`django-environ`,
`python-dotenv`), or with the standard library:

```python
# settings.py
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

env_file = BASE_DIR / ".env"
for line in env_file.read_text().splitlines() if env_file.exists() else []:
    key, _, value = line.partition("=")
    if key.strip() and not key.lstrip().startswith("#"):
        os.environ.setdefault(key.strip(), value.strip())

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

INSTALLED_APPS = [
    # django.contrib.admin and the rest of Django's defaults…
    "dbs",
]

MIDDLEWARE = [
    # Django's defaults, AuthenticationMiddleware among them…
    "dbs.security.middleware.DBSSecurityMiddleware",
]

DBS_BACKUP_DIR = os.environ.get("DBS_BACKUP_DIR", str(BASE_DIR / "backups"))
DBS_SCHEDULER = os.environ.get("DBS_SCHEDULER", "thread")
```

`DBSSecurityMiddleware` goes below `AuthenticationMiddleware`; above it, the guard cannot see
who is signed in, and `manage.py check` says so. `DBS_PASSPHRASE` is read straight from the
environment, so it needs no line in `settings.py`. No `urls.py` change is needed: the panel
mounts itself inside the admin you already have.

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py dbs upgrade      # checks everything above and says what is missing
```

Every setting is listed in the [settings reference](reference/settings.md).

## Backup commands

```bash
python manage.py dbs backup backup.dbs                  # write an encrypted backup
python manage.py dbs validate backup.dbs --passphrase   # check the blocks and decrypt
python manage.py dbs restore backup.dbs --dry-run       # rehearse; changes nothing
python manage.py dbs restore backup.dbs                 # restore for real
```

`manage.py dbs`, `manage.py django_dbs` and `manage.py django-dbs` are one command, and each
subcommand also exists on its own (`dbs_backup`, `dbs_restore`, …). Every option is in the
[command reference](reference/commands.md).

**A backup never replaces a file.** `dbs backup PATH` refuses a path that already exists. It
writes the backup beside it, readable by its owner alone, verifies it end to end, and only
then moves it into place. A missing or unreadable source file stops the backup and names the
file; `--allow-missing-files` backs up without it and lists what it left out.

**Backups stream.** Rows are read in batches from one database snapshot and files in chunks,
while other threads compress, encrypt, add parity and write. Memory stays flat however large
the project grows, and a restore reads the file the same way.

## Large tables and large values

Rows are read in pages keyed on the primary key, at most 500 rows or 8 MiB a page, so no
database driver holds a whole table in memory. A model with binary, text or JSON fields starts
at one row a page and grows the page from the row sizes it measures. A value of 1 MiB or more
goes into the backup without another copy, so backing up or restoring a 100 MB row takes DBS
about three times its size, on top of the database driver's own copies. One row may be up to
256 MiB.

- **PostgreSQL and MySQL.** A backup reads inside one `REPEATABLE READ` transaction, started
  `WITH CONSISTENT SNAPSHOT` on MySQL, so every page sees the same moment while the site keeps
  writing. A table holding values larger than MySQL's `max_allowed_packet` cannot be restored
  there; `dbs upgrade` warns when it is below 64 MiB.
- **SQLite.** WAL mode lets the site keep writing while a backup reads. `dbs upgrade` prints
  the `OPTIONS` that turn it on.

## A backup on standard output

```bash
python manage.py dbs backup --stream > /mnt/elsewhere/backup.dbs
```

`--stream` writes the backup to standard output and keeps the same bytes in `DBS_BACKUP_DIR`
(or `--output-dir`), named `PREFIX-YYYYMMDD-HHMMSSZ.dbs`, where `PREFIX` is
`DBS_BACKUP_PREFIX` (`backup` by default) or `--prefix`. Messages go to standard error, and
its last line is a JSON summary: `{"name", "size", "sha256"}`. If standard output breaks
mid-way, the backup still finishes on the server, the command exits 0 and the summary adds
`"kept_on_server": true`. At most five streamed backups are kept per prefix.

`--progress-seconds N` adds a first line on standard error naming the backup and its partial
file, `{"progress": {"name", "partial", "moment"}}`, then `{"progress": {"bytes": n}}` every N
seconds. This is how the DBS manager takes a backup: it knows which file to wait for if the
connection breaks, and resumes from where it stopped.

`--prefix`, `--output-dir` and `--progress-seconds` work only with `--stream`.

## Choosing what to back up

By default DBS finds every model, treats `FileField` and `ImageField` as files to embed, and
keeps relations intact. Every row is backed up, including rows the default manager hides.
Models with `managed = False` are left out, since the project does not own their tables, and
a multi-table child always brings its parent rows.

To configure a model, register it in a `dbs.py` inside your app. Once anything is registered,
only registered models are backed up:

```python
# myapp/dbs.py
from dbs import FieldType, ModelBackup, backup_registry
from .models import Invoice


@backup_registry.register(Invoice)
class InvoiceBackup(ModelBackup):
    overrides = {
        "scanned_pdf_path": FieldType.FILE_PATH,  # a path column: embed the file it names
        "render_cache": FieldType.EXCLUDE,        # leave this column out
    }
    file_roots = ["/srv/myapp/uploads"]           # extra file trees, also restore roots
```

`FieldType` has `VALUE` (store the column as it is, the default), `FILE` (a file field),
`FILE_PATH` (a path to embed) and `EXCLUDE`. A `ModelBackup.get_queryset()` narrows the rows.

`DBS_EXCLUDE_MODELS` skips models on top of the built-in exclusions: content types,
permissions, the admin log, sessions, and DBS's own records apart from the session guard's
policy and known locations. Prefix a label with `-` to back up one the defaults skip, an
unmanaged model included:

```python
DBS_EXCLUDE_MODELS = ["myapp.AuditRow", "-sessions.Session", "-legacy.Customer"]
```

Only regular files are read. A FIFO, socket or device, or a link that leaves its root, is
skipped and reported, so nothing in a file tree can hang a backup.

## Other databases

`--database ALIAS` backs up from, or restores into, another database alias; rows, files and
lookups all come from that alias.

## Next

- [The panel](panel.md): schedule, health and the audit trail in the admin.
- [Restoring](restoring.md): merge or replace, files, and passphrases.
