# Command reference

There are two commands:

- **`python manage.py dbs`**, inside a Django project: backups, restores, the schedule, health,
  the audit trail and upgrades.
- **`django_dbs`**, the [DBS manager](../manager.md), outside any project: it looks after the
  projects on your servers.

## In a project: `manage.py dbs`

`manage.py dbs` with no subcommand prints an overview. `manage.py django_dbs` and
`manage.py django-dbs` are the same command, and every subcommand also exists on its own as
`dbs_backup`, `dbs_restore`, `dbs_validate`, `dbs_schedule`, `dbs_connection`, `dbs_health`,
`dbs_audit`, `dbs_key`, `dbs_security`, `dbs_ai` and `dbs_upgrade`.

### `dbs backup OUTPUT`

Writes an encrypted backup to `OUTPUT`.

| Option | |
|---|---|
| `--passphrase P` · `--passphrase-stdin` | The passphrase, instead of the one DBS finds (prefer stdin: an argument is visible to other local processes) |
| `--database ALIAS` | Read rows, files and lookups from this database |
| `--allow-missing-files` | Back up without a missing or unreadable file, and list it |
| `--no-compress` · `--no-verify` | Skip compression, or the read-back check after writing |
| `--block-size N` · `--kdf-time N` · `--kdf-memory KIB` | The block size, and the Argon2id cost for this backup |

It refuses an `OUTPUT` that already exists, writes the backup beside it readable by its owner
alone, verifies it end to end, and only then moves it into place. It reports which source the
passphrase came from.

### `dbs backup --stream`

Writes the backup to standard output and keeps the same bytes on the server. It takes the
options above except `OUTPUT`, plus:

| Option | |
|---|---|
| `--prefix P` | The file name prefix (default `DBS_BACKUP_PREFIX`, `backup`) |
| `--output-dir DIR` | Where the server's copy goes (default `DBS_BACKUP_DIR`) |
| `--progress-seconds N` | Report the backup's name and its bytes on standard error every N seconds |

These three work only with `--stream`. See [A backup on standard output](../project.md#a-backup-on-standard-output).

### `dbs restore INPUT`

| Option | |
|---|---|
| `--dry-run` | Load everything in a transaction that is rolled back; write no files; name every file that would be refused |
| `--flush` | Delete the rows the backup covers first, so the restore replaces instead of merging |
| `--no-data` · `--no-files` | Restore only the files, or only the rows |
| `--database ALIAS` | Restore into this database |
| `--passphrase P` · `--passphrase-stdin` | The passphrase, instead of the one DBS finds |

See [Restoring](../restoring.md).

### `dbs validate INPUT`

Without options it checks the structure and every block. `--passphrase` also decrypts: given
bare, it uses the passphrase DBS finds; given a value, that one. `--passphrase-stdin` reads it
from standard input. A wrong passphrase is reported as an error, not a traceback.

### `dbs schedule`

Runs backups on a schedule, in its own process (use it with `DBS_SCHEDULER = "command"`).

| Option | |
|---|---|
| `--once` | Take one backup now and exit |
| `--interval 6h` · `--output-dir DIR` · `--prefix P` · `--keep 1-5` | Run this plan instead of the panel's |
| `--database ALIAS` · `--no-compress` · `--no-verify` · `--block-size` · `--kdf-time` · `--kdf-memory` | As for `dbs backup` |

With none of `--interval`, `--output-dir`, `--prefix` or `--keep`, it follows the panel's
schedule: it checks every minute, takes the same database lease as the in-process scheduler
and backs up only while the panel's schedule is on. With any of them it runs that plan, every
`24h` unless `--interval` says otherwise. It never prompts, so it needs `SECRET_KEY` or
`DBS_PASSPHRASE`. `SIGTERM` stops it at once. Run one fixed-plan scheduler per output folder.

### Other subcommands

| Command | What it does |
|---|---|
| `dbs health [--json]` | Grades the last backup's age, the last validation, the newest file, the backup folder, disk space, the passphrase, panel jobs and the scheduler, each `ok`, `info`, `warn` or `error` |
| `dbs audit [verify]` | Walks the audit trail's hash chain and prints the first broken link, or the head of the chain |
| `dbs connection [--json]` | What the DBS manager reads from this project: folders, Python, `manage.py`, settings module, backup folder, file roots, `.env` path, version and, on a server, its host, SSH user and host key fingerprints. In a container (`"container": true`) those last three come back empty. Never a passphrase |
| `dbs key [--show]` | Where the passphrase comes from; `--show` prints it |
| `dbs security [ACTION] [USER]` | `status` (the default), `unlock USER`, `policy`, `retrain`, `reset-baseline USER`, `events`, `purge`. `purge` removes telemetry only, never audit rows |
| `dbs ai` | `--agents`, `--check`, `--print`, `--root DIR`; see [AI assistants](../ai-assistants.md) |

### `dbs upgrade`

Checks the project against the installed version, applies pending DBS migrations, refreshes
installed AI instructions, and prints the exact line to add for anything it will not edit
itself. See [Upgrading](../upgrading.md).

| Option | |
|---|---|
| `--check` | Change nothing; exit non-zero when an item needs action (warnings leave it passing) |
| `--offline` | Skip the check for a newer release on PyPI |
| `--self [--to X.Y.Z] [--yes] [--system-python]` | Install the newest release, or `--to` one, after showing the pinned `pip install` and asking (`--yes` answers for a script). Inside a virtualenv only, unless `--system-python`. Run `dbs upgrade` again afterwards to finish |
| `--backups DIR` | Convert backups written in an older format into new files beside them |

`--to` needs `--self`, and `--self --offline` needs `--to`. A backup that cannot be read
forward stops `--backups`; giving it up needs an interactive terminal and an exact typed
phrase, and the message offers installing the older version that reads it first.

## The manager: `django_dbs`

`django_dbs`, `django-dbs` and `dbs` are one command, and `python -m dbs.manager COMMAND` is the
same when the script is not on your `PATH`. Every command takes `--data-dir PATH`, and every one
but `paths` takes `--database-url URL`. `django_dbs AREA VERB --help` lists each command's
options.

### Running and accounts

| Command | |
|---|---|
| `run` | `--port`, `--host`, `--trusted-proxy CIDR`, `--allow-insecure-http`, `--terminal admins\|master\|off`, `--no-browser`; see [Start it](../manager.md#start-it) |
| `paths` | Where the data folder, database, backups, log and sealing key are |
| `createuser NAME [--role ROLE] [--password-stdin]` | Add an account. The first is always the master; later ones are `admin`, `operator` or `viewer` |
| `password NAME [--password-stdin]` | Set a new password |
| `account list` · `role NAME ROLE` · `disable NAME` · `enable NAME` · `reset-2fa NAME` | Manage accounts; giving `master` hands the role over |
| `export [FILE] [--with-backups] [--passphrase-stdin]` | The database and keys in one encrypted file |
| `import FILE [--replace] [--yes] [--passphrase-stdin]` | Install an export; see [Moving the manager](../manager.md#moving-the-manager-itself) |
| `mcp [--as NAME]` | The MCP server for Claude; see [AI assistants](../ai-assistants.md) |
| `--version` | The installed version |

### Working with servers and applications

These take `--as NAME` (the account to act as; it defaults to the only one), `--json` (print
exactly what the web API returns) and `--password-stdin` (read your account password when an
action asks for it). A server or an application is named by its name or its id; a backup, a
plan or a `.env` version by the id `list` prints.

**`server`**

| Verb | Arguments and options |
|---|---|
| `list` | `--search TEXT` |
| `show` | `SERVER` |
| `add` | `NAME --host HOST [--port PORT] --user USER` (port 22 unless given), then one of `--key-file PATH`, `--ssh-password`, `--ssh-password-stdin`, `--generate-key`; `--key-passphrase`; `--host-key LINE` or `--yes` to accept the fingerprint shown |
| `edit` | `SERVER [--name] [--host] [--port] [--user]` and the sign-in options of `add` |
| `remove` | `SERVER [--yes]` |
| `check` | `SERVER…` or `--all` |
| `merge` | `SERVER --into SERVER` |
| `browse` | `SERVER [PATH]` |
| `public-key` | `SERVER` |
| `host-key` | `SERVER [--host-key LINE] [--yes]`: re-pin a changed key |
| `confirm-host-key` | `ID`: a person at a terminal confirms a key Claude read |
| `move` | `SERVER --to SERVER [--app NAME[=FOLDER]] [--name APP=NEW] [--skip-volume APP:VOLUME] [--no-plans] [--real] [--confirm-name NAME] [--resume JOB] [--sudo-password-stdin] [--no-sudo-password] [--source-sudo-password]`; see [Moving a server](../deploy-and-move.md#moving-a-server) |

**`app`**

| Verb | Arguments and options |
|---|---|
| `list` | `[--server SERVER] [--search TEXT]` |
| `show` | `APP` |
| `discover` | `SERVER [--folder FOLDER] [--deployment KEY=VALUE]…` |
| `add` | `NAME --server SERVER --folder FOLDER [--candidate N] [--backup-passphrase] [--deployment KEY=VALUE]…` and any setting below |
| `edit` | `APP [--name NAME] [--deployment KEY=VALUE]…` and any setting below |
| `remove` | `APP [--yes]` |
| `check` | `APP…` or `--all` |
| `passphrase` | `APP`: show the stored backup passphrase |
| `capture-passphrase` | `APP`: read it from the application, once, before the first backup |
| `deploy` | `APP [--real] [--confirm-name NAME]` |
| `deploy-steps` | `APP [--set FILE]` |

The settings `app add` and `app edit` take: `--kind host|compose|container`,
`--engine docker|podman`, `--compose-project`, `--compose-service`, `--compose-file PATH`
(repeat, in order), `--container`, `--project-dir`, `--workdir`, `--python`, `--manage`,
`--settings`, `--backup-dir`, `--env-path`, `--env-location host|container` and `--file-root
PATH` (repeat). The `--deployment` keys and their answers are listed under
[Add an application](../manager.md#add-an-application).

**`backup`**

| Verb | Arguments and options |
|---|---|
| `list` | `[--app APP]` |
| `take` | `APP…` or `--all` (one after another, with a summary; exits 1 if one failed) |
| `verify` | `BACKUP` |
| `restore` | `BACKUP --mode merge\|replace [--to APP] [--real] [--confirm-name NAME]` |
| `download` | `BACKUP [-o PATH]` |
| `upload` | `APP FILE` |
| `delete` · `undo-delete` | `BACKUP` |

**`plan`**

| Verb | Arguments and options |
|---|---|
| `list` | `[--app APP]` |
| `show` · `remove` · `run` · `pause` · `resume` | `PLAN` |
| `add` | `APP NAME --kind dbs\|archive\|collect [--path PATH]… [--pattern GLOB] (--every MINUTES \| --manual) [--keep 1-5] [--keep-remote 0-5] [--first-run WHEN] [--time-zone ZONE] [--disabled]` |
| `edit` | `PLAN` with the options of `add` (but `--kind`), `--name`, and `--enable` or `--disable` |
| `reschedule` | `PLAN --at WHEN` |

`--every` takes 60, 180, 360, 720, 1440 or 10080 minutes.

**`activity`, `env`, `files` and `redeploy`**

| Command | Arguments and options |
|---|---|
| `activity list` | `[--server SERVER] [--app APP] [--action ACTION] [--status queued\|running\|succeeded\|failed] [--limit N]` |
| `activity show` | `ENTRY` |
| `env list` · `env pull` | `APP` |
| `env compare` | `VERSION OTHER` |
| `env reveal` · `env push` | `VERSION` |
| `files list` | `APP [PATH]` |
| `files download` | `APP PATH [-o PATH]` |
| `files upload` | `APP FOLDER FILE` |
| `files mkdir` | `APP FOLDER NAME` |
| `files delete` | `APP PATH [--yes]` |
| `redeploy start` | `--from APP --to APP [--backup ID] [--env ID] [--flush] [--real] [--confirm-name NAME]` |
| `redeploy revert` | `JOB [--real] [--confirm-name NAME]` |

**From a script.** Secrets are typed at a prompt or read from standard input, never passed as
arguments. A confirmation takes `--yes`; a real `backup restore`, `app deploy`, `server move`,
`redeploy start` or `redeploy revert` takes `--confirm-name NAME` instead, the name a person
would type.
