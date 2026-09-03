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

`SIGTERM` stops the loop immediately. Run one scheduler per output directory. Retention
only touches files matching `prefix-YYYYMMDD-HHMMSSZ.dbs`.

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
