# DBS command reference

All of these are subcommands of `manage.py dbs`. `manage.py django-dbs` is the same
command under its old name, and the original `dbs_backup`, `dbs_restore`, `dbs_validate`
and `dbs_schedule` commands still work unchanged.

## `dbs backup OUTPUT`
`--passphrase`, `--passphrase-stdin`, `--database`, `--no-compress`, `--no-verify`,
`--block-size`, `--kdf-time`, `--kdf-memory`.

Reports which source the passphrase came from, so a surprising key is visible.

## `dbs restore INPUT`
`--passphrase`, `--passphrase-stdin`, `--database`, `--no-data`, `--no-files`,
`--dry-run`, `--flush`.

Merging is the default. `--flush` clears the backed-up models first so the restore
replaces. `--dry-run` performs the real load inside a transaction it rolls back and writes
no files. Always suggest a dry run before a restore onto anything that matters.

## `dbs validate INPUT`
`--passphrase` takes an optional value; given bare it uses the derived passphrase.
Without it, only structure and block integrity are checked.

## `dbs schedule`
`--interval`, `--output-dir`, `--prefix`, `--keep`, `--push`, `--keep-remote`,
`--database`, `--once`, plus the `dbs backup` cost flags.

With none of the plan flags (`--interval`, `--output-dir`, `--prefix`, `--keep`, `--push`,
`--keep-remote`) and the panel's schedule turned on, it follows the panel: it ticks every
minute and takes the same database lease as the in-process scheduler, so both can run
safely. With plan flags it runs that plan, as before.

`SIGTERM` stops the loop immediately. Run one fixed-plan scheduler per output directory.
Retention only touches files matching `prefix-YYYYMMDD-HHMMSSZ.dbs`.

## `dbs health [--json]`
Grades the last backup's age against the schedule, the last validation, whether the newest
file is on disk, the backup directory, disk space, the passphrase, the scheduler's last
check-in and recent failures, each `ok`, `info`, `warn` or `error`.

## `dbs connection [--json]`
Prints what the DBS manager needs to reach this project: host, SSH user, project directory,
Python, manage.py, settings module, backup directory, file roots, `.env` path, version and
host key fingerprints. Never a passphrase.

## `dbs key [--show]`
Reports where the passphrase comes from; `--show` prints it. Archive the output before
rotating `SECRET_KEY`.

## `dbs security ACTION [USERNAME]`
`status`, `unlock USER`, `policy`, `retrain`, `reset-baseline USER`, `events`, `purge`.

`unlock` is the escape hatch when the guard has locked someone out. It always works from a
shell regardless of what the detector decided.

## `dbs ai`
`--agents`, `--check`, `--print`, `--root PATH`.

Installs the DBS instructions into `.claude/skills/django-dbs/`. `--check` exits non-zero
when the installed copy has drifted, which is what you want in CI.

## `dbs upgrade`
`--check`, `--self`, `--backups DIR`, `--offline`, `--yes`.

Checks the project against the installed version, applies pending DBS migrations and
refreshes installed AI instructions, and prints the exact settings lines for anything it
will not edit itself. `--check` changes nothing and exits non-zero when something is
outstanding, which is what CI wants.

`--backups DIR` reads each container's format version and converts anything older, writing
a new `.converted` file and leaving the original in place. It never deletes, moves or
overwrites a backup. A file it cannot read forward stops the command; accepting that loss
needs an interactive terminal and an exact typed phrase, and **an assistant must never do
it** — stop and tell the developer instead.

Also reachable as `manage.py dbs_upgrade` and `manage.py dbs-upgrade`.

## `django_dbs` (the manager, outside any project)
`run [--port] [--host] [--no-browser] [--data-dir] [--database-url]`, `export [FILE]
[--with-backups]`, `import FILE [--replace]`, `createuser NAME`, `password NAME`, `paths`.
