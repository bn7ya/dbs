# DBS command reference

All of these are subcommands of `manage.py dbs`. `manage.py django_dbs` and
`manage.py django-dbs` are the same command, and the original `dbs_backup`, `dbs_restore`, `dbs_validate`
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
`--prefix`, `--output-dir`, `--progress-seconds N`, plus the options above except `OUTPUT`.

Writes the backup to standard output and keeps the same bytes in `DBS_BACKUP_DIR` (or
`--output-dir`) as `PREFIX-YYYYMMDD-HHMMSSZ.dbs`. Messages go to standard error; the last
line is a JSON summary `{name, size, sha256}`. When standard output breaks, the backup still
finishes on the server, the command exits 0 and the summary adds `kept_on_server: true`. At
most five streamed backups per prefix are kept. `--progress-seconds N` writes a first line
`{"progress": {"name", "partial", "moment"}}` naming the backup and its partial file, then
`{"progress": {"bytes": n}}` every N seconds. The DBS manager takes backups this way, with
the passphrase on `--passphrase-stdin`, and uses the first line to resume a transfer whose
connection broke.

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
`--passphrase-stdin` reads it from standard input. Without either, only structure and block
integrity are checked. A wrong passphrase is reported as an error, not a traceback.

## `dbs schedule`
`--interval`, `--output-dir`, `--prefix`, `--keep` (1 to 5), `--database`, `--once`, plus the
`dbs backup` cost flags.

With none of the plan flags (`--interval`, `--output-dir`, `--prefix`, `--keep`) it follows
the panel, whether its schedule is on yet or not: it ticks every minute and takes the same
database lease as the in-process scheduler, so both can run safely, and it backs up only
while the panel's schedule is on; `--once` takes one backup now either way. With plan flags
it runs that plan; so does a project that still sets `DBS_SCHEDULE_INTERVAL` while the
panel's schedule is off.

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
Prints what the DBS manager reads from this project: project directory, Python, manage.py,
settings module, backup directory, file roots, `.env` path and version, and on a server the
host, SSH user and host key fingerprints. `"container": true` says it runs in a container,
whose hostname, user and host keys say nothing about the server, so they come back empty. The
manager's discovery runs it itself; nobody pastes it anywhere. Never a passphrase.

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
will not edit itself. `--check` changes nothing and exits non-zero when an item needs
action, which is what CI wants; warnings are printed and leave it passing. `--self`
installs one exact release (the newest, or `--to`), after
showing the pinned `pip install` command and asking; `--yes` answers for a script.

`--backups DIR` reads each container's format version and converts anything older, writing
a new `NAME.v2.dbs` file beside it and leaving the original in place. It never deletes,
moves or overwrites a backup. A file it cannot read forward stops the command; accepting
that loss needs an interactive terminal and an exact typed phrase, and **an assistant must
never do it** — stop and tell the developer instead.

Also reachable as `manage.py dbs_upgrade`.

## `django-dbs` (the manager, outside any project)
Installed with `pip install django-dbs` under three equal names: `django-dbs`, `django_dbs`
and `dbs`.

`run [--port] [--host] [--trusted-proxy CIDR] [--allow-insecure-http]
[--terminal admins|master|off] [--no-browser]`, `export [FILE] [--with-backups]`,
`import FILE [--replace] [--yes]`, `createuser NAME [--role admin|operator|viewer]`,
`password NAME`, `account list|role|disable|enable|reset-2fa`, `paths`. Each takes
`--data-dir`, and all but `paths` take `--database-url`.

Everything the manager's interface does is also a command, on the same data:
- `server list|show|add|edit|remove|check|merge|browse|public-key|host-key|confirm-host-key`
  — a server is an SSH machine: address, user, credentials, host key, container engines
- `app list|show|discover|add|edit|remove|check|passphrase|capture-passphrase|deploy|deploy-steps`
  — an application is one Django project on a server
- `backup list [--app]|take APP…|--all|verify|restore|download|upload|delete|undo-delete`
- `plan list|show|add|edit|remove|run|reschedule|pause|resume` (`--keep 1-5`,
  `--keep-remote 0-5`, `--every MINUTES`, `--first-run WHEN`, `--time-zone ZONE`)
- `activity list [--server] [--app]|show`, `env list|pull|compare|reveal|push`,
  `files list|download|upload|mkdir|delete`
- `redeploy start --from APP --to APP [--backup ID] [--env ID] [--flush] [--real]`,
  `redeploy revert JOB_ID [--real]` (a move, or a deploy's safety backup)

Each takes `--as NAME` (the account to act as; defaults to the only one), `--json` (the web
API's output) and `--password-stdin` (for actions that need the account password). Accounts
have roles (master, admin, operator, viewer) and a command refuses what the role does not
allow. Secrets are prompted for or read from stdin, never passed as arguments; confirmations
need `--yes` from a script, and a real `backup restore`, `app deploy`, `server move`,
`redeploy start` or `redeploy revert` needs `--confirm-name NAME` instead, the name a person
would type. `server add` confirms the host key, signs in and checks which
engines answer. `server confirm-host-key ID` is for a person at a real terminal: never run it
on their behalf.

`app discover SERVER --folder F` lists the places a folder's application runs, best first:
on the server itself, in a Compose service whose working folder is in F, or in a container
with a bind mount from F, under Docker or Podman, with its Python, `manage.py`, settings, the
host paths of its backup folder and file roots, its `.env` candidates and its problems
(`container_not_running`, `dbs_missing`, `dbs_too_old`, `backup_dir_not_mounted`). It runs
nothing in a folder another account can write to. `app add NAME --server S --folder F
[--candidate N]` adds one and checks it; `--kind host|compose|container`,
`--engine docker|podman`, `--compose-service`, `--compose-file`, `--container`,
`--project-dir`, `--workdir`, `--python`, `--manage`, `--settings`, `--backup-dir`,
`--env-path`, `--env-location host|container` and `--file-root` override what was found.
Overriding what runs (`--kind` to `--settings`) asks for the account password; what discovery
found is added without it.
`app capture-passphrase` runs once, before an application's first backup; an application's
backup passphrase must never change afterwards. The SSH user needs the `docker` group or
rootless Podman as itself; backups and the check never use `sudo` (`engine_permission_denied`).
`--deployment KEY=VALUE` (repeat it) on `app discover`, `app add` and `app edit` records how
the developer says the project runs (`runs_in`, `engine`, `database`, `database_runs`,
`settings_from`, `source`, `process_manager`, `web_server`); it ranks discovery and needs no
password. `server move SOURCE --to TARGET` plans moving a server's applications onto another
server and, with `--real`, installs what it lacks with `sudo`, carries each application and
restores its data. `--app NAME[=FOLDER]` chooses the applications and their folders, `--name
APP=NEW` a name (otherwise `NAME (TARGET)`), `--skip-volume APP:VOLUME`, `--no-plans`,
`--resume JOB`, `--sudo-password-stdin` after `--password-stdin`, `--no-sudo-password` when
none is needed, `--source-sudo-password` to read what the old server's SSH user cannot.

`app deploy-steps APP --set FILE` takes a JSON list of steps from the fixed catalogue —
`git_pull` (`remote`, `branch`), `compose_pull`, `compose_build` (`pull`), `compose_up`
(`services`), `restart`, `systemd_user_restart` (`unit`), `pip_install` (`requirements`),
`migrate`, `collectstatic`, each with `timeout_minutes` 1 to 120 — at most twelve, with the
account password. `app deploy APP` rehearses (read-only checks); `--real` checks the
application, takes a safety backup, records the `.env`, runs the steps and checks again.

`django_dbs mcp [--as NAME]` is an MCP server over stdio for Claude
(`claude mcp add dbs -- django_dbs mcp`). Its tools read everything but secrets, add and
check servers once a person confirmed the host key, discover, add and check applications,
take, verify and save backups, add and run plans, keep `.env` versions (key names only) and
rehearse restores, moves, deploys (`rehearse_deploy`) and reverts. It never takes the account
password and has no tool that reveals a secret, restores, moves, deploys or reverts for real,
changes deploy steps, keeps fewer backups, saves a file the manager keeps encrypted, removes
or deletes, or reaches the console or the terminal.

The interface adds a console (`POST /api/console/`: one command line as the signed-in
account, without `backup download|upload`, `files download|upload`, `server add|edit`,
`app passphrase`, `env reveal`, `app deploy-steps --set` and `mcp`) and, for admins, a
terminal on a server or inside an application's container, with the account password every
time.

`python -m dbs.manager COMMAND` is the same, for when pip put `django_dbs` in a folder that
is not on `PATH`.
