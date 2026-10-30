# The panel at `/admin/dbs/`

Once `dbs` is installed beside `django.contrib.admin` and migrated, the panel is at
**`/admin/dbs/`**. There is no `urls.py` change to make.

| Page | What it does |
|---|---|
| **Dashboard** | The schedule, health, recent backups and the session guard at a glance |
| **Take a backup** | Writes a backup to `DBS_BACKUP_DIR` in the background, then offers it for download |
| **Restore** | Restores an uploaded `.dbs` file, starting with a dry run that changes nothing |
| **Schedule** | Turns scheduled backups on, sets how often and how many to keep, 1 to 5 |
| **Health** | Whether the last backup is recent, valid and still on disk; disk space, the passphrase and how panel jobs run |
| **Audit** | Every backup, restore, validation, prune, download and change made in the panel, sealed in a hash chain |
| **Security** | The session guard: its level, trusted networks and recent verdicts |
| **Connection** | What a DBS manager needs to reach this project: the server's SSH address and the project's folder, and the server folder behind a container's mount |
| **Wiki** | The manual, inside the admin |

The **backups list** shows every backup this project wrote, with *download* and *restore* for
each one kept in `DBS_BACKUP_DIR`.

**Superusers only.** There is no permission to grant for it, because the panel can download
and overwrite your whole database. On your first visit, a short wizard asks which networks
you sign in from and how strict the [session guard](session-guard.md) should be.

**Backups stay on this server.** The panel pushes nothing anywhere. Copies elsewhere are the
[DBS manager](manager.md)'s job: it connects to this server and pulls the backups.

## Backup frequency

Open **Schedule**, tick *enabled*, and choose an interval (`30m`, `6h`, `1d`, at least five
minutes) and how many backups to keep, from 1 to 5 (5 by default). A project with several
databases picks the one to back up. That is all: the schedule runs inside your web workers.

On the first request a worker serves, a small background thread starts and checks once a
minute whether a backup is due. Every worker runs one, and a lease in the database makes sure
exactly one backup is taken per interval, however many workers or servers you run. The lease
lasts two minutes and is renewed every 30 seconds while a backup runs, so a long backup is
never started twice. A run is recorded as running before it starts; if its worker dies, the
next tick takes the backup again, and if that one dies too, the schedule waits for the next
interval.

To run the schedule in a process of its own, set `DBS_SCHEDULER = "command"` and run
`python manage.py dbs schedule` under systemd; it follows the same panel setting.
`DBS_SCHEDULER = "off"` switches scheduling off.

| Deployment | `DBS_SCHEDULER` |
|---|---|
| gunicorn, uWSGI with `--enable-threads`, Daphne, uvicorn | `"thread"` (the default) |
| uWSGI without threads, or several hosts each with its own `DBS_BACKUP_DIR` | `"command"`, with one `dbs schedule` process |
| Serverless, or backups taken only by a DBS manager | `"off"` |

When a DBS manager also backs this project up, its check warns that the panel's schedule is
on too. Turn one of them off, or plan fewer backups in the manager.

## What is kept

The server keeps at most five backups in `DBS_BACKUP_DIR`. After each scheduled or panel
backup, retention removes the oldest of this project's backups beyond the schedule's number,
and only those:

- It touches only files named for this project and database: `backup-YYYYMMDD-HHMMSSZ.dbs`
  for the `default` database and `backup-ALIAS-YYYYMMDD-HHMMSSZ.dbs` for another, with
  `DBS_BACKUP_PREFIX` in place of `backup`. Two backups in the same second get `-2`, `-3` and
  so on. Anything else in the folder is left alone.
- Backups are ordered by the time recorded when they were taken, then the time written inside
  the file, and only then by name.
- A name stamped in the future, a link, or a file that is not a DBS backup is never counted
  and never removed.
- The newest backup that passed verification is always kept, and a backup that failed
  verification never takes one of the places.

Unfinished temporary files older than an hour are cleared from the folder. `dbs backup PATH`
removes nothing, and `dbs backup --stream` keeps at most five per prefix.

## Taking a backup and restoring from the panel

*Take a backup*, restoring a stored backup and restoring an upload all run in the background,
outside the web request, so a worker timeout never cuts one short. The page refreshes every
few seconds until the job ends, then shows the outcome, with a download link for a finished
backup. Only one backup or restore runs at a time. *Take a backup* needs `DBS_BACKUP_DIR`,
and a download only ever streams a file already written there.

Every backup in `DBS_BACKUP_DIR` has a **restore** link. The page opens with *Dry run*
ticked; a real restore needs the file name typed out. *Replace instead of merge* clears the
backed-up rows first. [Restoring](restoring.md) explains what a restore does.

## Panel jobs run in a process of their own

A panel backup, a panel restore and a scheduled backup each run in a child process,
`python -m dbs.job_process`, never in the web worker that served the request:

- The child reads what to do, passphrase included, from its standard input, never from its
  arguments or its environment.
- It lowers its priority, holds the job's leases, and stops itself when it runs too long or
  uses too much memory.
- The worker that started it watches it. If the child dies, the job fails, its leases are
  freed and its partial file is removed.

| Setting | Default | Meaning |
|---|---|---|
| `DBS_JOB_TIME_LIMIT` | `"6h"` | How long a job may run, as `30m`, `6h` or `1d` |
| `DBS_JOB_MEMORY_LIMIT` | `"2G"` | How much memory a job may use, as `512M` or `2G`; `0` for no limit |
| `DBS_JOB_NICE` | `10` | How much the child lowers its priority |
| `DBS_JOB_PYTHON` | the project's Python | The interpreter that runs the child |
| `DBS_JOB_BOOTSTRAP` | `django.setup` | A dotted path to the callable that sets Django up in the child, such as `configurations.setup` |
| `DBS_JOB_PROCESS` | `True` | `False` runs jobs in a thread of the web process, with no time or memory limit |

A job stopped at its limit fails with `time_limit` or `memory_limit`; one whose process ended
any other way fails with `killed`, and the job page says which. A backup that runs out of
space, cannot write its folder, finds a read-only disk or loses its database connection
records `disk_full`, `permission_denied`, `read_only` or `database_failed`. Older backups are
never touched, and retention does not run after a failure. A child that finds another process
has taken its job over stops itself, and the job carries on in that process.

The child starts with the worker's `DJANGO_SETTINGS_MODULE`, working folder and `sys.path`.
Where the web server embeds Python (uWSGI, mod_wsgi), DBS uses the `python3` of the
environment it runs in, so set `DBS_JOB_PYTHON` to the project's virtualenv Python when that
is not the one. `manage.py dbs upgrade` starts the interpreter, checks that it loads the
project and says what to set when it cannot; `manage.py dbs health` names the interpreter and
the limits.

## Health

**Health** grades each check `ok`, `info`, `warn` or `error`:

- the last backup's age against the schedule: fine up to 1.5 times the interval, late up to
  three times, failing beyond that;
- the last validation, and whether the newest backup file is still on disk;
- whether `DBS_BACKUP_DIR` is writable and has room for two more backups;
- whether a passphrase is available for unattended backups;
- whether panel jobs run in their own process, with which interpreter and limits;
- when the scheduler last checked in, and the most recent failure.

`python manage.py dbs health` prints the same report, and `--json` gives it to a monitoring
system along with the panel's schedule (`enabled`, `interval_seconds`, `keep`, `mode`).

## The audit trail

Each backup, restore, validation, retention prune, download, export and schedule change
writes one row: what happened, to which file, its size and SHA-256, how long it took and
whether it succeeded, with an error code when it did not. Every change made in the panel is
recorded too, under the superuser who made it. A backup records itself the same way however
it was started (the panel, the schedule, `manage.py`, cron or an SSH session), so the trail
describes the process, never which program asked for it. Writing the trail never fails a
backup: if the database refuses the row, the backup still completes and the problem is
logged.

The trail is tamper-evident. Once a row finishes, it is sealed with the SHA-256 of the row
before it and its own content, so a row changed or deleted afterwards breaks the chain there:

```bash
python manage.py dbs audit verify
```

It prints the first broken link, or the head of the chain, which you can keep somewhere else
to compare later. No DBS command deletes audit rows.
