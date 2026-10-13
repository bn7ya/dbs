# DBS command reference

All of these are subcommands of `manage.py dbs`. `manage.py django-dbs` is the same
command under its old name, and the original `dbs_backup`, `dbs_restore`, `dbs_validate`
and `dbs_schedule` commands still work unchanged.

## `dbs backup OUTPUT`
`--passphrase`, `--passphrase-stdin`, `--database`, `--no-compress`, `--no-verify`,
`--block-size`, `--kdf-time`, `--kdf-memory`, `--allow-missing-files`.

Reports which source the passphrase came from, so a surprising key is visible. It refuses an
`OUTPUT` that already exists, writes the backup beside it readable by its owner alone,
verifies it end to end and only then links it into place. A source file that is missing or
unreadable stops the backup and names it; `--allow-missing-files` backs up without it and
lists what was left out. Rows, files and lookups are read from `--database`.

## `dbs backup --stream`
`--prefix`, `--output-dir`, plus the options above except `OUTPUT`.

Writes the backup to standard output and keeps the same bytes in `DBS_BACKUP_DIR` (or
`--output-dir`) as `PREFIX-YYYYMMDD-HHMMSSZ.dbs`. Messages go to standard error; the last
line is a JSON summary `{name, size, sha256}`. When standard output breaks, the backup still
finishes on the server, the command exits 0 and the summary adds `kept_on_server: true`. At
most five streamed backups per prefix are kept. The DBS manager takes backups this way, with
the passphrase on `--passphrase-stdin`.

## `dbs restore INPUT`
`--passphrase`, `--passphrase-stdin`, `--database`, `--no-data`, `--no-files`,
`--dry-run`, `--flush`.

Merging is the default: an existing row only takes the fields the backup carries. `--flush`
deletes the rows the backup covers first so the restore replaces. `--dry-run` performs the
real load inside a transaction it rolls back, writes no files, never touches a sequence,
names every file a restore would refuse and exits non-zero when there is one. Always suggest
a dry run before a restore onto anything that matters.

## `dbs validate INPUT`
`--passphrase` takes an optional value; given bare it uses the derived passphrase.
Without it, only structure and block integrity are checked.

## `dbs schedule`
`--interval`, `--output-dir`, `--prefix`, `--keep` (1 to 5), `--database`, `--once`, plus the
`dbs backup` cost flags.

With none of the plan flags (`--interval`, `--output-dir`, `--prefix`, `--keep`) it follows
the panel, whether its schedule is on yet or not: it ticks every minute and takes the same
database lease as the in-process scheduler, so both can run safely, and it backs up only
while the panel's schedule is on. With plan flags it runs that plan; so does a project that
still sets `DBS_SCHEDULE_INTERVAL` while the panel's schedule is off.

`SIGTERM` stops the loop immediately. Run one fixed-plan scheduler per output directory.
Retention keeps at most five, only touches files matching `prefix-YYYYMMDD-HHMMSSZ.dbs`, and
always keeps the newest backup that passed verification.

## `dbs health [--json]`
Grades the last backup's age against the schedule, the last validation, whether the newest
file is on disk, the backup directory, disk space, the passphrase, the scheduler's last
check-in and recent failures, each `ok`, `info`, `warn` or `error`.

## `dbs audit verify`
Walks the audit trail's hash chain and prints the first broken link, or the head of the
chain. Also `manage.py dbs_audit`. No DBS command deletes audit rows.

## `dbs connection [--json]`
Prints what the DBS manager needs to reach this project: host, SSH user, project directory,
Python, manage.py, settings module, backup directory, file roots, `.env` path, version and
host key fingerprints. Never a passphrase.

## `dbs key [--show]`
Reports where the passphrase comes from; `--show` prints it. Archive the output before
rotating `SECRET_KEY`. The passphrase itself must never change.

## `dbs security ACTION [USERNAME]`
`status`, `unlock USER`, `policy`, `retrain`, `reset-baseline USER`, `events`, `purge`.

`unlock` is the escape hatch when the guard has locked someone out. It always works from a
shell regardless of what the detector decided. `status` shows the idle timeout and whether
the anomaly model can run. `purge` removes telemetry only, never audit rows.

## `dbs ai`
`--agents`, `--check`, `--print`, `--root PATH`.

Installs the DBS instructions into `.claude/skills/django-dbs/`. `--check` exits non-zero
when the installed copy has drifted, which is what you want in CI.

## `dbs upgrade`
`--check`, `--self`, `--to VERSION`, `--system-python`, `--yes`, `--backups DIR`,
`--offline`.

Checks the project against the installed version, applies pending DBS migrations and
refreshes installed AI instructions, and prints the exact settings lines for anything it
will not edit itself. `--check` changes nothing and exits non-zero when something is
outstanding, which is what CI wants. `--self` installs one exact release (the newest, or
`--to`) with the extras installed here, after showing the pinned `pip install` command and
asking; `--yes` answers for a script.

`--backups DIR` reads each container's format version and converts anything older, writing
a new `NAME.v2.dbs` file beside it and leaving the original in place. It never deletes,
moves or overwrites a backup. A file it cannot read forward stops the command; accepting
that loss needs an interactive terminal and an exact typed phrase, and **an assistant must
never do it** — stop and tell the developer instead.

Also reachable as `manage.py dbs_upgrade` and `manage.py dbs-upgrade`.

## `django_dbs` (the manager, outside any project)
Needs `pip install "django-dbs[manager]"`.

`run [--port] [--host] [--trusted-proxy CIDR] [--allow-insecure-http] [--no-browser]`,
`export [FILE] [--with-backups]`, `import FILE [--replace] [--yes]`,
`createuser NAME [--role admin|operator|viewer]`, `password NAME`,
`account list|role|disable|enable|reset-2fa`, `paths`. Each takes `--data-dir`, and all but
`paths` take `--database-url`.

Everything the manager's interface does is also a command, on the same data:
- `server list|show|add|edit|remove|check|discover|browse|public-key|host-key|confirm-host-key|passphrase|capture-passphrase`
- `backup list|take|verify|restore|download|upload|delete|undo-delete` (`take SERVER…` or `--all`)
- `plan list|show|add|edit|remove|run` (`--keep 1-5`, `--keep-remote 0-5`), `activity list|show`
- `env list|pull|compare|reveal|push`, `files list|download|upload|mkdir|delete`
- `redeploy start --from SERVER --to SERVER [--backup ID] [--env ID] [--flush] [--real]`,
  `redeploy revert MOVE_ID [--real]`

Each takes `--as NAME` (the account to act as; defaults to the only one), `--json` (the web
API's output) and `--password-stdin` (for actions that need the account password). Accounts
have roles (master, admin, operator, viewer) and a command refuses what the role does not
allow. Secrets are prompted for or read from stdin, never passed as arguments; confirmations
need `--yes` from a script. `server add` confirms the host key, finds the project and its
Python, and checks the server. `server confirm-host-key ID` is for a person at a real
terminal: never run it on their behalf. `server capture-passphrase` runs once, before a
server's first backup; a server's backup passphrase must never change afterwards.

For a project whose Django runs in a Docker Compose service, `server add|edit` take
`--runtime compose --compose-service SERVICE [--compose-file FILE]…` with `--project-dir` set
to the folder holding the Compose files; `--python` and `--manage` are then paths inside the
container. The manager runs `docker compose exec -T SERVICE python manage.py …` from that
folder. Discovery finds such a project by itself when the service is running and its image
has django-dbs.

`django_dbs mcp [--as NAME]` is an MCP server over stdio for Claude
(`claude mcp add dbs -- django_dbs mcp`). Its tools read everything but secrets, add and
check servers once a person confirmed the host key, take, verify and save backups, add and
run plans, keep `.env` versions (key names only) and rehearse restores, moves and reverts. It
never takes the account password and has no tool that reveals a secret, restores, moves or
reverts for real, keeps fewer backups, saves a file the manager keeps encrypted, removes or
deletes.

`python -m dbs.manager COMMAND` is the same, for when pip put `django_dbs` in a folder that
is not on `PATH`.
