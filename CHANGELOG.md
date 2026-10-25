# Changelog

All notable changes to this project are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.8.0] - Unreleased

A server and the Django projects on it are now separate things: the DBS manager adds a server
by its SSH address, then finds each application on it from a folder, on the server itself, in
a Compose service or in a container, under Docker or Podman. It backs them up, schedules and
reschedules them, deploys them in place or moves them, keeps their backups on the manager's
own machine and restores them, all without SSH or the Django admin, and offers a console and
a terminal in the browser. Panel backups and restores leave the web process for a limited
child process, large tables are read in pages, a 100 MB row takes DBS about three times its
size, and a stream whose connection broke resumes where it stopped. `pip install django-dbs`
installs everything, and the manager answers to `django-dbs`, `django_dbs` and `dbs`.

### Added

- **Applications.** A server holds its address, pinned host key, sealed credentials and the
  container engines it has; an application is one Django project on it, with where it runs
  (`kind`: host, compose or container; `engine`: docker or podman), its paths inside and on
  the host, its mounts, its `.env` and where that file lives. Backups, plans, `.env`
  versions, files, deploys and moves belong to an application, so one server runs several.
  `/api/applications/`, the terminal's `app` area and the MCP tools follow the split.
- **Discovery from a folder.** Given a server and a folder, the manager lists the folder,
  asks Docker and Podman which containers belong to it (Compose labels, working folder, bind
  mounts), joins replicas, finds each container's Python and `manage.py`, asks django-dbs
  for its settings, maps container paths to host paths through the mounts and offers the
  `.env` files Compose and django-dbs name, best candidate first. Nothing runs in a folder,
  or a project below it, that another account can write to.
- **Docker and Podman.** Every command in a container goes through the engine; a restore
  streams the backup into the container over standard input as the container's own user, a
  `.env` kept in the image is read and replaced in place, and stale partials and restore
  leftovers are swept inside the container. The check reports each engine, its Compose and
  whether the SSH user may use it (`engine_permission_denied`).
- **Scheduling.** A plan has a first run and an IANA time zone; daily and weekly plans keep
  their local time across daylight saving. Plans can be rescheduled (later runs follow from
  the new time), paused and resumed (at the next beat after now, with no catch-up) from the
  interface, the API (`…/reschedule/`, `…/pause/`, `…/resume/`) and the terminal.
- **Deploy in place.** An application keeps up to twelve deploy steps from a fixed catalogue:
  `git_pull` (fast-forward only), `compose_pull`, `compose_build`, `compose_up`, `restart`,
  `systemd_user_restart`, `pip_install`, `migrate` and `collectstatic`, each a fixed argument
  list with validated names and its own time limit. A deploy checks the application, takes a
  safety backup, records its `.env`, runs the steps and checks it again (`manage.py check`,
  `migrate --check`), recording the git HEAD and image before and after. Its rehearsal only
  reads. One that stopped after a step ran offers its safety backup back.
- **A console** at `/console` and `POST /api/console/` runs one `django_dbs` command line as
  the signed-in account, without the commands that read the manager's own disk or stdin.
- **A terminal.** An admin opens a shell on a server, or inside an application's container
  or folder, from the browser, with the account password every time. It closes on sign-out,
  a password or role change, 15 minutes without input, a minute without a poll or two hours
  in all; at most four run at once, two per account. The audit row records where, how long
  and the bytes each way, never what was typed or shown. `django_dbs run --terminal` (or
  `DBS_MANAGER_TERMINAL`) narrows it to the master or switches it off.
- **Every backup in one place.** `/backups` lists every application's backups beside the
  storage each uses.
- **Resumed transfers.** A 0.8 server names the backup it is writing and reports progress
  every 30 seconds; when the connection breaks, the manager reconnects after 5, 15 and 45
  seconds, waits while the server finishes, pulls only the rest and checks the whole digest
  before it decrypts to verify. A stream stops early only when nothing arrives for 15
  minutes; a backup has a day in all.
- **Panel jobs in their own process.** Panel backups, restores and scheduled runs run in
  `python -m dbs.job_process`, which reads its spec and passphrase from standard input,
  lowers its priority (`DBS_JOB_NICE`) and stops at `DBS_JOB_TIME_LIMIT` (6 hours) or
  `DBS_JOB_MEMORY_LIMIT` (2 GiB). A child that dies fails its job as killed and frees its
  leases. `DBS_JOB_PROCESS = False` keeps jobs in the web process; `DBS_JOB_PYTHON` and
  `DBS_JOB_BOOTSTRAP` cover servers whose interpreter or setup differs.
- **`dbs backup --stream --progress-seconds N`** names the backup on standard error at once
  and reports the bytes written; `dbs connection --json` says whether the project runs in a
  container; `dbs health --json` carries the panel's schedule; `dbs validate
  --passphrase-stdin`.
- **Failure codes.** A backup that fails for lack of space, a refused folder or a lost
  database records `disk_full`, `permission_denied`, `read_only` or `database_failed`.
- **Upgrade steps.** `ContribViewsRemoved`, `CommandNames`, `LegacyPartials`,
  `SSHTargetKeys`, `RetiredExtras`, `PanelJobProcess`, `MySQLReads` and `SQLiteWrites`.
- **Test suites** for 1,000 tables and a million rows, 100 MB rows, failing backups in real
  child processes, a Django site under load during a backup (with a published report),
  several instances of one project, two hundred applications in one manager, Docker and
  rootless Podman Compose projects over OpenSSH, and an upgrade from 0.7.0.

- **One list of exceptions.** `dbs.exceptions` holds everything DBS raises, each a
  `DBSError`: `Busy`, `ScheduleError` and `StreamInterrupted` move there (their old import
  paths still work), and `HostUnreachable` and `AuthenticationFailed` (a
  `ConfigurationError`) name the two common SSH failures. The README lists each exception
  and when it is raised, and what DBS does to your project when it fails.
- `dbs.security.W004`: `manage.py check` names entries in `DBS_TRUSTED_PROXIES` or
  `DBS_TRUSTED_NETWORKS` that the guard ignores.

### Changed

- **A DBS failure never fails your project's request.** Pages outside the admin are
  untouched by it. While the session guard cannot check a session, the admin stays
  readable and refuses changes, downloads and exports with `503`, and a session the guard
  decided to end is refused even when ending it failed. A failed sign-in that cannot be
  recorded still just fails, in a savepoint of its own, and a scheduler thread that cannot
  start leaves the request alone. Each of these is logged to `dbs`.
- `write_backup` and `create_backup` refuse an empty passphrase with `ConfigurationError`,
  which would let anyone open the backup; restore and validate still read one written so.
- A server or application check whose connection drops, or whose probe times out, is
  recorded as failed with the reason (`connection_lost`, `remote_command_timed_out`)
  instead of reporting an engine, a file or django-dbs as missing; the server keeps the
  engines the last check found.
- **`pip install django-dbs` installs everything DBS uses**: scikit-learn for the guard,
  paramiko for SSH, and djangorestframework, waitress and keyring for the manager. The
  `guard`, `manager`, `ssh` and `all` extras remain as empty names for this release. The
  core still imports none of them outside `dbs/security`, `dbs/transports` and
  `dbs/manager`.
- **Three command names.** `django-dbs`, `django_dbs` and `dbs` all start the manager's
  command line, and `manage.py dbs`, `manage.py django_dbs` and `manage.py django-dbs` are
  the same command.
- **Large tables and large values.** Rows are read in pages keyed on the primary key, so
  MySQL no longer buffers a whole table; models with binary, text or JSON fields start with
  one-row pages and grow from the measured row size; values of 1 MiB or more are spliced
  into the frame without copies. Backing up or restoring a 100 MB row takes DBS about 3
  times its size, down from 5 to 6.5, on top of the copies the database driver makes itself.
- **MySQL reads one snapshot.** A backup opens `REPEATABLE READ` with a consistent snapshot,
  so every page sees the same moment.
- **The interface** is rebuilt around servers and applications, blue, light and minimal.
- **The manager's SQLite** starts write transactions immediately on Django 5.1 or later, so
  concurrent jobs no longer fail with "database is locked".
- **Remote django-dbs** must be 0.7.0 or newer; health always runs.
- The manager serves on 16 threads.

### Removed

- **`dbs.contrib`**, the original in-request backup and restore views.
- The `dbs-upgrade` command alias and the hyphen-alias shim; `SSHTarget.from_dict` no
  longer reads `user` and `key_file`; the sweep of pre-0.7 `.part` files; the
  `HiddenRows` upgrade step; `retention.prune_directory`, `prune_remote` and
  `stale_backups`; the format 1 writers (format 1 backups still restore, validate and
  convert).
- The connection snippet in the manager's wizard: give it the SSH address and the folder.

### Fixed

- A podman-compose project read as stopped, and its backups as failed, because the manager
  asked Compose for flags podman-compose lacks and read the last line of its output.
- A move could restore a backup that failed verification; it now refuses with
  `backup_quarantined`.
- `dbs validate` with a wrong passphrase ended in a traceback.
- The manager could make a new sealing key, leaving every sealed secret unreadable, when its
  key was in a system keychain that stopped answering or lost the entry, or when
  `DBS_MANAGER_KEY_STORE=file` was set for a key the keychain holds. It now refuses to start
  and says why.
- Failures that went unreported now reach the `dbs` log: a panel backup or restore that
  fails, a retention run that fails after a good panel backup (also recorded as a failed
  `backup.prune`), a backup folder retention cannot list, leftovers that cannot be swept,
  uploads and partial files that cannot be removed, a backup folder that cannot be synced to
  disk, a schedule the database cannot read (a warning now), a scikit-learn that breaks on
  import, a two-factor secret that cannot be opened, and a backup whose output cannot be
  read back to verify.
- An error inside Reed-Solomon decoding other than the decoder's own was reported as damage
  beyond repair.

### Security

- The terminal is admin only, asks the account password for every shell, closes on
  sign-out, a password or role change, and records no keystroke or output. The MCP server
  and the console never reach it.
- Deploy steps are fixed argument lists from a catalogue; no command line or argument list
  is taken from a request. A `git_pull` names its remote and branch together, or neither.
- Adding an application, and changing what it runs (where it runs, its container or Compose
  service, its folders, its Python, its `manage.py` and its settings module), asks for the
  account password at any time. The Python must be named like one and `manage.py` must be a
  `manage.py`, so neither can be read as an option. The MCP server adds an application only as
  discovery found it.
- Discovery leaves out containers whose names or Compose labels could be read as options, and
  the manager reads or replaces no `.env` on a server whose folder, or the folder it links
  into, another account can write to (`env_folder_shared`).
- The panel's invariant stays: it runs no remote command and keeps no SSH credential.

## [0.7.0] - 2026-10-13

Backups now stream: a multi-threaded engine writes container format 2 with flat memory
however large the project, and restores read it the same way. The server keeps its backups
and the DBS manager pulls them, so the panel's SFTP targets and console are gone, and so is
`dbs-client`. The server keeps at most five backups and never prunes the newest good one.
`pip install django-dbs` is the backup library alone; the guard, the manager and the SSH API
are extras. The manager gains roles, a master account, two-factor sign-in and a sealing key
in the system keychain, moves a project with a fresh backup of the old server and can revert
the move, and asks for a person before Claude pins a host key. A long list of restore and
retention fixes closes ways a backup or a restore could lose data.

### Added

- **Container format 2 and a streaming engine.** `write_backup(output, passphrase, ...)`
  streams a backup to a path that does not exist yet or to any binary file object and
  returns a `BackupSummary` (size, SHA-256, records, files, skipped files, models and the
  repair margins). Rows are read in batches from one snapshot in the calling thread while a
  compression pool, an encoding thread and a writer thread work behind bounded queues; a
  failure in any stage stops them all and never leaves a partial file. `workers` spreads
  parity and encryption over more threads. `restore_backup` and `validate_backup` take
  bytes, a path or a seekable file object, and read format 2 as a stream. `write_backup` and
  `BackupSummary` are exported from `dbs`.
- **`dbs backup --stream`** writes the backup to standard output and keeps the same bytes in
  `DBS_BACKUP_DIR` (or `--output-dir`) under the usual name for `--prefix`, written through a
  private partial file and linked into place. Messages go to standard error, whose last line
  is a JSON summary `{name, size, sha256}`. When standard output breaks the backup still
  finishes, the command exits 0 and the summary adds `kept_on_server: true`. The server keeps
  at most five streamed backups per prefix, and partial files older than an hour are swept.
- `dbs backup --allow-missing-files` and `allow_missing_files=True` back up without the
  source files that are missing or unreadable, list them in the backup and append them to
  `skipped_files`.
- `DBS_RESTORE_PATH_MAP` maps old absolute roots to new ones, for a restore onto a server
  whose paths differ; `FILE_PATH` rows are pointed at the moved files. A dry run lists the
  files a restore would refuse in `RestoreResult.files_refused`, and `dbs restore --dry-run`
  names them and exits non-zero. `restore_backup(registry=...)` restores with a given
  configuration.
- New exceptions: `BackupError` and `MissingSourceFiles`; `ConnectionLost` and
  `RemoteTimeout` for SSH sessions.
- **A tamper-evident audit trail.** Each finished row is sealed with the SHA-256 of the row
  before it and its own content. `manage.py dbs audit verify` (also `dbs_audit`) prints the
  first broken link, or the head of the chain to keep elsewhere.
- **Panel jobs.** *Take a backup*, restoring a stored backup and restoring an upload run in a
  background thread, one at a time, on a job page at `/admin/dbs/backuprecord/jobs/<id>/`
  that refreshes until the job ends.
- System checks `dbs.security.W001` (`X-Forwarded-For` trusted with no proxy network),
  `W002` (`DBSSecurityMiddleware` above `AuthenticationMiddleware`) and `W003` (scikit-learn
  missing). `dbs security status` shows the idle timeout and the anomaly model's state.
- `dbs upgrade --self --to X.Y.Z` installs exactly that release; `--system-python` lets
  `--self` change an interpreter outside a virtual environment.
- `dbs upgrade` steps for this release: dependencies, guard extra, manager extra, manager
  keychain, off-site copies, dbs-client, retention, audit chain, backup format, forwarded
  addresses, unmanaged models, missing source files, backup paths, restore path map and
  remote command limits. The session guard step also reports a misplaced middleware.
- `SSHTarget` takes `keepalive_interval` (15 seconds), `io_timeout` (30 seconds) and
  `command_timeout` (6 hours). `SSHSession.stream()` runs a command and writes its standard
  output to a file as it arrives; `is_alive()`, `answers()` and an `on_activity` hook report
  the connection.
- **The manager collects and streams.** A DBS backup run first collects the backups waiting
  on the server under its server's or plan's name, then streams a fresh one with
  `dbs backup --stream`, checks its size and SHA-256 and decrypts it end to end, and only
  then removes the server's copies it recorded, keeping `keep_remote`. A broken stream ends
  as `kept_on_server`, not failed, and the next run collects it. `backup take --json`, the
  MCP `take_backups` tool and job details report `kept_on_server`, `pulled`, `released`,
  `quarantined` and `outcome`.
- **Quarantine.** A backup that fails verification in the manager is kept as
  `NAME.quarantined` with the reason in `failure` (migration `0004_backupfile_failure`),
  never restored (`backup_quarantined`) and never counted; the five newest per server and
  plan are kept.
- **Manager roles.** Every account is a master, an admin, an operator or a viewer
  (`dbs/manager/permissions.py`), checked in every service, so the interface, the REST API,
  the terminal and the MCP server share one rule; a refusal is `403 role_required`.
  Rehearsals need an operator, real restores and moves an admin. `/api/auth/me/` reports the
  role and its capabilities, and the interface hides what the role cannot do.
- **The master account** is the one made at setup (on upgrade, the oldest account; every
  other becomes an admin). Only it manages accounts, on the **Accounts** page,
  `/api/accounts/`, or `django_dbs createuser NAME --role ROLE` and
  `django_dbs account list|role|disable|enable|reset-2fa`. It hands the role over with its
  password and a code, or with `django_dbs account role NAME master`.
- **Two-factor sign-in.** Every web sign-in takes the password, then a TOTP code or one of
  ten single-use recovery codes. An account enrolls at its next sign-in with a QR code; *Your
  account* makes new recovery codes behind the password. Endpoints:
  `/api/auth/two-factor/`, `/api/auth/two-factor/enrollment/` (and `confirm/`),
  `/api/auth/password/` and `/api/auth/recovery-codes/`; `/api/auth/login/` answers the next
  step.
- **Passwords last 30 days** for web sign-in. An expired one, or one the master asked to
  replace, leaves the session able only to change it; the terminal and the MCP server say so.
  `django_dbs password NAME` resets the clock. New accounts choose their own password at
  their first sign-in.
- **The sealing key in the system keychain**, through keyring, wherever one works;
  `DBS_MANAGER_KEY_STORE=file|keychain` chooses. The manager warns when the key sits in a
  file next to the data and refuses to start when the keychain and a key file disagree.
- `django_dbs run --trusted-proxy CIDR` (also `DBS_MANAGER_TRUSTED_PROXY`) believes the
  forwarded scheme and client only from a TLS proxy's range, with `Secure`, `HttpOnly`
  cookies and HSTS; `--allow-insecure-http` accepts plain HTTP beyond loopback.
- **Connection liveness.** Each server records `connection_state`, `last_seen_at` and
  `last_connection_error` (migration `0007_server_connection_state`); a probe reaches every
  server not seen for five minutes. The interface shows a connection dot per server and a
  running job's connection; `/api/activity/` entries carry `connection`, `server list` and
  `server check` a CONNECTION column, and long terminal jobs a progress line every 30
  seconds.
- **Remote deadlines.** Where a server has `timeout`, every remote command runs under it
  and an overrun reads `remote_command_timed_out`. A server whose last command ended unseen
  refuses new backups, restores and moves until its deadline passes (`server_settling`).
  Starting the manager frees the locks of jobs whose process is gone.
- **Moving to a new server** backs up the old server now when it answers, records the new
  server's `.env`, takes a safety backup of the new server's data, then pushes the `.env`,
  migrates, restores and checks. A move that stops after changing the new server names the
  step and can be reverted: the recorded `.env` goes back and the safety backup is restored.
  `POST /api/redeploy/{id}/revert/`, `django_dbs redeploy revert MOVE_ID [--real]`, and the
  MCP tool `rehearse_revert`, which only rehearses.
- **Person-confirmed host keys.** The MCP `fingerprint_host` tool holds the key it read for
  ten minutes and returns a confirmation id; `add_server` pins it only after a person
  confirms it on the Servers page (`/api/servers/host-keys/`, `…/{id}/confirm/`,
  `…/{id}/reject/`) or with `django_dbs server confirm-host-key ID` at a real terminal.
- One-time download links: `POST /api/backups/{id}/download/` and
  `POST /api/files/{server}/download/` trade the account password for a link that works
  once, for a minute.
- `django_dbs import` builds the new installation in a staging folder and swaps it in; the
  one it replaces is moved to `<data-dir>.before-import-<stamp>`, never deleted, and a start
  after an interrupted swap finishes it. `--yes` accepts an export sealed with another key.
- CI runs both suites on Python 3.9 to 3.13 with Django 4.2, 5.2 and 6.x, on SQLite,
  PostgreSQL 17 and MySQL 8.4, on every dependency's lowest version, against a real OpenSSH
  server, and under a corruption stress test; a release publishes only after it passes.
  `SECURITY.md` names supported versions, reporting, timelines, scope and the threat model.

### Changed

- **`pip install django-dbs` installs the backup library alone**: Django, cryptography,
  argon2-cffi, reedsolo and numpy. Extras add the rest: `guard` (scikit-learn, for the
  session guard's detector), `ssh` (paramiko, for `dbs.transports`), `manager`
  (djangorestframework, waitress, paramiko, keyring, for `django_dbs`) and `all`. Every
  dependency is capped below its next major version. `django_dbs` without the manager extra
  prints the one `pip install` line it needs and exits 1.
- **New backups are container format 2.** Both copies of every block are written, the second
  64 blocks after the first, so a burst of damage never reaches both; each block is one
  AES-256-GCM chunk authenticated together with the header, with Reed-Solomon parity and a
  keyed BLAKE2b tag; the header and trailer are each written twice with a checksum; no plain
  hash of the data is stored. Format 1 backups still validate and restore.
  `DBS_MAX_PAYLOAD_BYTES` now applies to format 1 only.
- A backup refuses Argon2id costs above `DBS_KDF_TIME_COST = 10` and
  `DBS_KDF_MEMORY_COST = 262144` KiB, the limits every reader enforces.
- Reed-Solomon parity is computed with numpy, and an intact block is read without decoding:
  format 1 encoding goes from about 0.4 to 53 MB/s and a clean validation from 0.3 to
  112 MB/s. Many-to-many members are fetched once per batch of rows.
- **Backups.** `dbs backup PATH` and `create_backup(output=PATH)` refuse a path that exists,
  write beside it, verify and only then link the file into place. A missing or unreadable
  source file stops the backup. Only regular files are read; FIFOs, sockets, devices and
  links that leave their root are skipped and reported. Unmanaged models are left out unless
  registered or listed as `-app.model`. A multi-table child brings its parent rows. Every
  model, file and lookup is read from `--database`. Backups record their model order.
- **Restores.** Rows load in the recorded order, parents first. A merge updates only the
  fields a backup carries. `--flush` deletes only the rows the backup covers. Every file
  target is checked before any row loads, and a `ModelBackup`'s `file_roots` are restore
  roots; files are staged beside their targets and moved into place when the rows commit.
  A real restore only ever raises a sequence.
- **Retention.** The server keeps at most five backups: the schedule keeps 1 to 5 (default
  5; `DBS_SCHEDULE_KEEP` defaults to 5, `dbs schedule` refuses more, as it does for
  `--keep`, and the panel reads a larger value as 5), and the migration lowers larger
  values. Backups are ordered by recorded time, then the time in the file, then the name;
  only this project's prefix and database alias are touched
  (`backup-ALIAS-YYYYMMDD-HHMMSSZ.dbs` for a database other than `default`); the newest
  verified backup is always kept; a failed one never takes a place; two backups in one
  second are named `-2`, `-3`.
- The scheduler holds a two-minute lease renewed every 30 seconds, records a run as running
  before it starts, moves the next run only after it finishes, and retries a killed run once.
- *Take a backup* writes to `DBS_BACKUP_DIR` and needs it; downloads stream a finished file.
- Every write through the DBS admin is audited, and so are panel downloads and the contrib
  views' export and restore. Panel rows keep the acting username after the user is deleted.
  A failure that is not a DBS error is recorded as `unexpected`.
  `dbs security purge` removes telemetry only and records a `security.purge` row.
- **The session guard.** `DBS_TRUSTED_PROXIES` lists proxy networks instead of counting
  hops. Learning mutes only the model; the rules and both thresholds stay active. The personal
  forest is refit in the background from the newest 2000 rows, at most every 15 minutes or
  200 requests. Changes to users, groups, permissions and passwords count as high-risk.
- `dbs upgrade --backups` writes a conversion to `<name>.v2.dbs` (then `-2`, `-3`), readable
  by its owner alone, validated before it takes the name, and reports one converted earlier.
- `dbs upgrade --self` installs one exact version with the extras installed here, prints the
  pinned command and asks first (`--yes`), names the requirement files to pin it in, and
  refuses a source checkout. Without `--self`, `dbs upgrade` recommends pinning the newest
  release.
- **Manager retention.** A plan keeps 1 to 5 backups here (5 by default) and 0 to 5 on the
  server (0 by default), clamped by migration `0006_plan_retention_limits` and on import; a
  one-off take keeps the five newest and leaves none on the server. Keeping fewer asks for
  the account password, and the MCP `update_plan` tool refuses it. Two plans of one server
  cannot share a name that differs only in case or punctuation.
- The manager asks for the account password before every download that decrypts (folder
  archives, collected and uploaded files, a `.env` through the Files tab), before deleting a
  backup and before deleting a server. The terminal saves downloads readable by their owner
  alone.
- The MCP `add_server` tool takes `confirmation` instead of `host_key`; `download_backup`
  refuses files the manager keeps encrypted, writes them readable by their owner alone and
  never overwrites. The MCP instructions, the terminal help and the interface say a server's
  backup passphrase must never change.
- `django_dbs redeploy start` takes `--backup` only as the backup to restore when the old
  server does not answer (its newest by default), and `POST /api/redeploy/` accepts a null
  `backup`.
- `django_dbs run` refuses a non-loopback `--host` without `--trusted-proxy` or
  `--allow-insecure-http`. Sign-in failures count per address and per username, with a
  slow-down from 2 to 60 seconds that an address the account used in the last 30 days skips.
- The manager's SSH sessions send keepalives every 15 seconds and bound SFTP reads to 30
  seconds; on Linux the kernel drops a connection that stops answering.

### Removed

- **`dbs-client`**, `python -m dbs.client`, the `dbs.client` API, the `client` extra and
  `django_dbs server import-profiles`. The manager and its terminal do the same work;
  `dbs upgrade` points at them when a `dbs-client` config is left.
- **SFTP targets and the console.** The `BackupTarget` model and admin,
  `BackupRecord.target`, the schedule's push target and remote retention, the panel's push
  option, the console with its fixed actions and free-form shell, the dashboard's SFTP card,
  the wiki's targets page, and `dbs schedule --push` / `--keep-remote`. The settings
  `DBS_SSH_TARGETS`, `DBS_SCHEDULE_PUSH_TARGET`, `DBS_SCHEDULE_KEEP_REMOTE` and
  `DBS_ADMIN_CONSOLE_SHELL` no longer do anything. Migration `0005_pull_only_retention_chain`
  records each dropped target, without credentials, in the audit trail.
- The panel's *download to my browser* option, which built a backup inside the request.
- The move's folder-archive step, with `redeploy start --archive` and `--migrate` and the
  `archives` and `migrate` request fields.
- tomli from the runtime dependencies, and the unused `backup_invalid` error code.

### Fixed

- **A dry run could change sequences.** It now never touches one, and a real restore only
  raises a PostgreSQL sequence, never below its current value.
- **A merge restore overwrote fields the backup did not carry**, so `FieldType.EXCLUDE`
  fields lost their values and a NOT NULL excluded field without a default broke the
  restore.
- **`--flush` deleted every row of a model**, even when `ModelBackup.get_queryset` backed up
  only some of them, and dropped the links of excluded many-to-many fields.
- **On MySQL, `--flush` stopped with a foreign key error** whenever a row the backup does not
  cover pointed at one it replaces. As on PostgreSQL and SQLite, a replaced row may now be
  missing until the load puts it back, and a restore that would leave a link to a row it
  removed is refused, even one that loads no rows.
- **`--database` was not honoured**: a backup read rows, files and lookups from the default
  database.
- **A backup could replace an existing file**, and was written in place before it was
  verified.
- **A missing source file was skipped without a word**, and a FIFO in a file tree could hang
  a backup.
- **Files were written before the rows committed**, and stayed when the load failed.
- Restores loaded models in an order that could break foreign keys; a multi-table child was
  backed up without its parent rows.
- **One damaged byte in a header could hide a backup**, or make it look like an unknown future
  format. Only a header copy that verifies is used, so every byte of the front header is
  survivable while the back copy is intact.
- Retention ordered backups by name alone, counted future-stamped files, links and failed
  backups, could prune the newest good backup, and let two backups in one second overwrite
  each other.
- A scheduled backup took a six-hour lease and moved its next run before it started, so a
  killed run blocked the schedule for hours.
- Panel backups and restores ran inside the web request, so a worker timeout killed
  anything past a few megabytes.
- `dbs upgrade --backups` wrote `<name>.converted` with the umask's mode and could replace an
  existing file. `dbs upgrade --self` ran `pip install --upgrade` with no version and
  mistook a Debian `dist-packages` install for a source checkout.
- SFTP transfers were readable by other users while in flight; a push deleted a backup of
  the same name before uploading, and a pull replaced a local file.
- The schedule's page created the schedule row for staff without superuser who visited it.
- The manager hung on a dropped SSH connection, and a remote command had no deadline. On
  Windows every process looked alive, so a crashed job kept its lock.

### Security

- `X-Forwarded-For` is read only from a request whose peer is in `DBS_TRUSTED_PROXIES`;
  before, any client could choose its own address and land inside a trusted network. An
  address the guard cannot read counts as a new network.
- A flagged session could still create a superuser, change groups and permissions, or
  download a backup. It is now refused every change anywhere in the admin, and every download
  or export, the contrib views included.
- Learning mode switched enforcement off, and a purge put dormant accounts back into it. The
  session count survives purges, and the rules apply from the first request.
- The policy's idle timeout is enforced server-side. Telemetry stores the network and a keyed
  hash of the address instead of the address, and is purged automatically after
  `DBS_SECURITY_RETENTION_DAYS`; a purge no longer deletes the audit trail.
- The console, which could run free-form commands on remote servers from a browser, is gone.
- Format 2 bounds every header field and Argon2id cost before any work, and detects a
  reordered, swapped or truncated block through its authenticated position.
- Every local backup file and every temporary file it is written through is readable by its
  owner alone from the first byte; an SFTP upload is too, before its bytes arrive.
- The manager's secrets are sealed under a key kept in the system keychain where one works;
  a new data folder on Windows is limited to its owner; an import never deletes the
  installation it replaces.
- Claude can no longer pin a host key no person confirmed, make a plan keep fewer backups,
  or save a file the manager keeps encrypted.

## [0.6.0] - 2026-10-11

Everything the DBS manager does in its interface can now be done from a terminal with
`django_dbs` commands, or by Claude through `django_dbs mcp`, all on the same services. The
manager backs up and restores projects that run in Docker Compose, browses the server to pick
folders, and finds the server's django-dbs in whichever Python has it. Restores put
permissions and content types back on their own rows, a PostgreSQL backup reads every model
from one snapshot, and a block damaged in both copies is rebuilt from what each copy still
holds.

### Added

- **Projects in Docker Compose.** A manager server can say its Django runs in a Docker Compose
  service (`runtime`, `compose_service`, `compose_files`; *Where the project runs* in the
  wizard and the server's settings; `--runtime compose --compose-service SERVICE
  --compose-file FILE` in the terminal; the same fields over MCP). The manager then runs every `manage.py` command —
  the check, backups, restores, the passphrase and the redeploy's migrations — inside that
  service with `docker compose exec -T`, from the project folder, and moves backups in and out
  of the container with `docker compose cp`, removing the copies it made. Discovery asks Docker
  which services run beside a Compose file and finds the one whose Python has django-dbs. The
  check reports Docker's version and whether the service is running. Servers already in the
  manager keep running on the host; the manager's migration `0003_server_runtime` adds the
  fields and applies itself the next time any `django_dbs` command starts.
- `python -m dbs.manager` runs the manager, for when pip installs `django_dbs` into a folder
  that is not on `PATH`. The README and the panel's wiki explain the fix, and
  `python -m dbs.client` does the same for `dbs-client`.
- **Browse the server.** The manager's add-server wizard and server settings open the server's
  folders and files in a dialog, so the project, the backup folder, the allowed folders and the
  `.env` file are picked rather than typed. `GET /api/servers/{id}/browse/?path=` lists what the
  server's SSH user can read; it never writes.
- The wizard searches for the project as soon as the server is added, lists every project it
  finds, and fills in the rest for the one chosen. `POST /api/servers/{id}/discover/` accepts a
  `project_dir` to look inside one folder.
- **The manager from a terminal.** Everything the manager's interface does is also a
  `django_dbs` command: `server add|edit|remove|check|discover|browse|…`,
  `backup take SERVER… | --all`, `backup list|verify|restore|download|upload|delete`,
  `plan`, `activity`, `env`, `files` and `redeploy start`. The commands and the web API call
  the same services and validate with the same serializers, so a server added in one shows
  in the other, `--json` prints what the API returns, and the activity log records both
  under the account that acted (`--as NAME`, or the only account). Actions the interface
  guards with the account password ask for it here too, or read it with `--password-stdin`;
  secrets are prompted for or read from stdin, never taken as arguments. `server add`
  confirms the host key, finds the project and its Python, and checks the server.
- `django_dbs server import-profiles [dbs-client.toml]` adds the servers of a `dbs-client`
  config to the manager.
- **Claude can drive the manager.** `django_dbs mcp` is an MCP server over stdio
  (`claude mcp add dbs -- django_dbs mcp`), built in with no new dependency. Its 27 tools call
  the same services as the interface and the terminal: an overview, servers (add with an SSH
  password, a key file or a new key after you confirm the host key fingerprint; change, check,
  discover, browse), backups (take on several servers, verify, save, rehearse a restore),
  plans, activity, `.env` versions by key name, server files and a rehearsed redeploy. It never
  takes the account password, never returns a secret, and has no tool that restores or
  redeploys for real, removes, deletes, pushes a `.env` or re-pins a host key.
- `THIRD_PARTY_LICENSES.md` names the license of every package `pip install django-dbs`
  brings in, of what the manager's interface bundles, and of the development tools. It ships
  in the wheel and the sdist beside `LICENSE`.

### Changed

- The package declares its license as the SPDX expression `MIT` instead of a license
  classifier, so building from source needs setuptools 77 or later.
- The manager's cache lives in its database (table `dbs_manager_cache`, created by its migrations), so
  the per-server backup lock and the sign-in throttle hold across processes: a backup taken
  from a terminal and one `django_dbs run` schedules never run on one server together.
- A running job holds a database lease while it works, and `django_dbs run` starting up fails
  as interrupted only the jobs whose process is gone, not one a terminal is still running.

### Deprecated

- `dbs-client` prints a deprecation notice on every run and will be removed in a later
  release. `django_dbs server import-profiles` moves its servers into the manager, and
  `django_dbs backup take` replaces `dbs-client backup`. The `dbs.client` Python API is
  unchanged.

### Fixed

- A server whose django-dbs lives in a virtualenv was reported as not recognized. Discovery now
  tries every Python it can find — any virtualenv in or next to the project (found by its
  `pyvenv.cfg`, whatever its name), `~/.virtualenvs`, `python3`, `python` — and keeps the one
  that imports django-dbs. When the saved Python cannot, the check reports the error it got
  and suggests the Python that has django-dbs, applied with one click.
- A check that found django-dbs missing said the server's version "does not work with this
  manager". It now says django-dbs was not found.
- After one check that did not pass, the wizard could no longer save a corrected project
  folder or Python without the account password it never asks for. The setup window now stays
  open until a check passes.
- Choosing another project while the wizard was still reading the last one could save the new
  folder with the old project's Python and backup folder. *Next* now waits for the search to
  finish, and what was found is shown only for the folder in the field.
- **A restore could hand out the wrong permissions.** Content types and permissions are left
  out of a backup because `migrate` recreates them, but rows referred to them by id, and a
  database migrated in another order numbers them differently. Restored onto a fresh server,
  a group or a user could receive another model's permissions, and a generic relation could
  point at the wrong model, with no error. A relation to a model the backup does not carry is
  now written by natural key and found again by name on restore. A permission the target
  lacks is left out with a warning; a foreign key it cannot find stops the restore and names
  the row. Older backups still restore, with a warning naming the models they refer to by id.
- **A PostgreSQL backup taken while the project was in use could fail its own restore.** Each
  model was read in a snapshot of its own, so a row committed mid-backup could arrive without
  the row it points at. A backup now reads every model from one `REPEATABLE READ` snapshot.
- **Damage in both copies of one block was unrecoverable** even with every byte intact in one
  copy or the other. Such a block is now rebuilt codeword by codeword from both copies, with
  the bytes where they differ treated as erasures.
- `dbs schedule` with no plan flags followed the panel only when its schedule was already on
  at start; otherwise it ran a 24-hour loop of its own and never noticed the panel. It now
  always follows the panel, unless `DBS_SCHEDULE_INTERVAL` is still set, and `dbs upgrade`
  warns when `DBS_SCHEDULER = "command"` and the panel's schedule is off.
- `dbs backup` and `dbs schedule` given a folder they cannot write ended in a traceback; they
  now name the path and the reason. `dbs upgrade` checks that `DBS_BACKUP_DIR` can be
  written, and Health no longer reports a nested folder that is not created yet as
  unwritable.

### Security

- The manager runs a virtualenv's Python, or a project's `manage.py`, that it found by itself
  only when the folder is owned by the SSH user or root and nobody else can write to it
  (group write is accepted for the SSH user's own group, as a `002` umask leaves it). A
  virtualenv planted next to the project by another account on a shared server is never run,
  and a project folder you choose yourself is always used.
- The version probe no longer imports from the folder it runs in, so a `dbs.py` or `dbs/` in
  the project folder can neither run nor fake the reported version.
- Discovery runs commands on the server, so once a server's setup is over (an hour after it
  was added, or once a check has passed) it asks for the account password, as changing the
  server's settings already does. A `manage.py` placed through the Files tab can no longer be run
  by anyone who only holds a signed-in session.
- The ownership rule also covers the folder that holds a virtualenv or a found project, so one
  cannot be swapped out through a parent folder other accounts can write to.
- Browsing keeps at most 5000 entries of a folder and says when it stopped, and one search
  tries at most 8 Pythons, so neither a huge folder nor a home full of virtualenvs can tie up
  the manager.

## [0.5.0] - 2026-10-09

One `pip install django-dbs` now covers three uses, depending only on where you use it: the
backup library inside a project, a panel at `/admin/dbs/` that sets the backup frequency and
shows health and an audit trail with no extra setup, and the DBS manager, a local
application started with `django_dbs run` that looks after many servers and can move a
project onto a new one. The manager was a separate project, DBS Interface; it now ships
inside the package, prebuilt, with no Node, Docker, Redis or separate database needed.

### Added

- **Backup frequency in the panel.** `/admin/dbs/backupschedule/` turns scheduled backups on
  and sets the interval, the number to keep, and an optional SFTP push target. The schedule
  runs in a background thread that each web worker starts on its first request; a database
  lease and an advanced next-run time give one backup per interval however many workers or
  hosts run. `DBS_SCHEDULER` chooses `"thread"` (default), `"command"` or `"off"`.
  `manage.py dbs schedule` with no plan flags follows the panel.
- **Health.** A panel page and `manage.py dbs health [--json]` grade the last backup's age
  against the schedule, the last validation, the newest file on disk, the backup directory,
  free space, the passphrase, the scheduler's last check-in and recent failures.
- **Restore from the server side.** Any backup kept in `DBS_BACKUP_DIR` restores from its
  row in the panel, dry run first, with the file name typed for a real restore.
- **Connection details.** A panel page and `manage.py dbs connection [--json]` give the
  DBS manager everything it needs to reach the project, as one snippet.
- **The audit trail records outcomes.** `AuditEvent` gains `status`, `data`, `error_code`,
  `subject`, `started_at` and `finished_at`. `dbs backup`, `dbs restore`, `dbs validate`,
  scheduled backups, retention prunes and pushes each record what happened, to which file,
  with its size, SHA-256 and duration. A backup records itself the same way however it was
  started, and an audit write that fails never fails the backup.
- `dbs backup` records a `BackupRecord`, so command line and scheduled backups appear in the
  panel and can be restored from it.
- **The DBS manager**: `django_dbs run`, `export`, `import`, `createuser`, `password` and
  `paths`. It keeps everything in one data folder with a local SQLite database, opens the
  browser, and asks for a username and password on first run. It adds a dashboard, a guided
  add-server wizard (connection snippet, host key confirmation, generated keys, project
  discovery, version check, passphrase capture, test backup) and *Move to another server*,
  which pushes a saved `.env`, migrates, restores and unpacks archives on a new server.
- Upgrade steps for the audit migration, the schedule, the scheduler mode and the backup
  directory.

### Changed

- `paramiko`, `djangorestframework` and `waitress` are now dependencies, so the manager
  needs nothing beyond `pip install django-dbs`. None of them is imported unless used.
- `AuditEvent.target_name` holds up to 1024 characters.
- Leases and the backup schedule are left out of backups, so a restore onto a staging
  server does not bring an enabled schedule with it.

### Upgrading

`manage.py dbs upgrade` applies migrations `0003_audit_outcome` and `0004_schedule_lease`.
If you set `DBS_SCHEDULE_INTERVAL`, turn the schedule on once in the panel, or keep running
`dbs schedule --interval …` as before. Behind uWSGI without `--enable-threads`, set
`DBS_SCHEDULER = "command"` and run `manage.py dbs schedule`.

## [0.4.0] - 2026-10-06

An application that manages several servers keeps their credentials and host keys in its
own database. This release lets it connect the way such an application needs to: with a
private key held in memory, trusting exactly one pinned host key, and confirming that key
before trusting it. Backups also now include every row, including the ones a project's
default manager hides. Nothing in a project has to change to upgrade.

### Added

- `SSHTarget.host_key` pins a server's public key, written as `"<type> <base64>"`.
  Only that key is trusted for the host and port. The system known_hosts is not read, and
  combining it with `auto_add_host_key` is refused. `dbs-client.toml` accepts `host_key`
  on a server too.
- `fetch_host_key(host, port)` reads the key a server presents, without authenticating, so
  a person can compare its fingerprint before pinning it. It returns a `HostKey`, whose
  `fingerprint` reads exactly as `ssh-keygen -lf` prints it and whose `line` is ready to
  store as `host_key`.
- `HostKeyError`, a `ConfigurationError`, is raised when a server presents a key that does
  not match the trusted one, or one that is not trusted at all.
- `manage.py dbs upgrade` names the backed-up models whose default manager hides rows, so
  the backup change below is visible before the next backup runs.

### Fixed

- `ModelBackup.get_queryset()` reads through `model._base_manager` instead of
  `model._default_manager`. A default manager that filters rows — a soft-delete manager
  hiding `is_deleted=True`, a tenant-scoped manager — used to leave those rows out of the
  backup, and a restore then failed its constraint check wherever a visible row still held
  a foreign key to a hidden one. Restore and `flush` already used `_base_manager`; backup
  now matches them.
- Many-to-many links are read from the through table with `_base_manager` too, so a link
  from any row to a row the related model's default manager hides is kept.
- A private key held in memory (`SSHTarget(private_key=...)`, and the admin panel's SFTP
  targets with a pasted key) now loads. It was read through paramiko's base key class,
  which cannot parse a key, so every such connection failed before it was attempted.
  Ed25519, ECDSA and RSA keys load, with or without a passphrase.
- An unknown or changed host key on a target with `key_filename` was reported as a problem
  with the private key. It is now reported as a host key problem.
- `SSHSession.run(timeout=...)`, and so `exec_timeout` in `dbs-client.toml`, bounded each
  read but not the command. A command that printed nothing and never exited held the
  caller for ever. The timeout is now a deadline for the whole command: when it passes, the
  channel is closed and `DBSError` says the command timed out.
- A target with a password and `use_agent=False` no longer offers the local user's
  `~/.ssh` keys to the server. Local keys are looked for only when the agent is in use and
  no key is named.
- The `Panel` proxy model behind the control panel shipped in 0.3.0 without a migration, so
  `makemigrations --check` failed in every project with `dbs` installed. `0002_panel` adds
  it. `manage.py dbs upgrade` reports it as pending and applies it, like any other DBS
  migration.
  A test now fails whenever a model change ships without its migration.

### Changed

- Backups of a project with a filtering default manager grow by the rows it hides. To keep
  leaving them out, override `ModelBackup.get_queryset` for that model and return
  `model._default_manager.all()`.

### Security

- Backup manifests no longer expose database statistics, model labels, file names, or
  skipped-file paths before decryption.
- Local backup writes and SFTP transfers set owner-only `0600` permissions, including when
  replacing a destination that previously had broader permissions.
- Security regression coverage now exercises offline dictionary guesses, metadata
  confidentiality, and local and remote file permissions.

## [0.3.1] - 2026-09-03

Follows 0.3.0 on PyPI. It adds `manage.py dbs upgrade`, and fixes the time-dependent test
that made the 0.3.0 release run fail on its first attempt.

### Added

- `python manage.py dbs upgrade` checks a project against the installed version of DBS,
  applies what is safe to apply, and prints the exact settings lines for the rest. It knows
  the steps every release has needed so far: the tables 0.3.0 added, `scikit-learn`, the
  `django.contrib.admin` and middleware entries the panel and guard need, and the
  `DBS_EXCLUDE_MODELS` meaning that changed in 0.2.2 — that one silently altered behaviour
  for anyone who had written the setting expecting it to replace the defaults, and until now
  nothing detected it. It also reports when a newer release exists, and `--self` installs it
  unless this is a source checkout. `--check` changes nothing and exits non-zero when
  something is outstanding, which is what CI wants. Also spelled `manage.py dbs_upgrade` and
  `manage.py dbs-upgrade`.
- `dbs upgrade --backups DIR` reads each backup's container format version and converts
  anything older. Every backup written by any released DBS is version 1, which this version
  reads, so today it reports nothing to convert; it exists so that a future format change
  cannot strand files that already exist. Conversion chains across several versions, and a
  converted file is validated end to end before it counts.
- `dbs.container.format.container_version` reads a container's format version without
  requiring it to be the current one.
- `DBS_TEST_HOUR` shifts the clock for the whole test suite, so behaviour that depends on
  the time of day can be reproduced on demand instead of by chance. The guard, panel,
  console and base-model tests pass at all twenty-four hours.

### Fixed

- A regression test for the session guard asserted a specific verdict tier, and the guard
  scores hour-of-day as a feature. A first request from an unrecognised network scores
  0.72-0.82 during the day and 0.85-0.92 between midnight and 07:00 UTC, so above the
  balanced logout threshold the guard ended the session and the test's next request arrived
  anonymous. The behaviour was correct; the assertion was not. The test now pins the logout
  threshold out of reach and checks the recorded feature rows directly, so it asserts the
  invariant it cares about rather than the tier a score lands in.
- The two packaging tests added in 0.3.0 imported `tomllib` unconditionally, which is
  standard library only from Python 3.11, so they failed on the 3.9 and 3.10 test matrix
  cells. They now use the same `tomli` fallback the rest of the project does.

### Security

- Nothing in `dbs upgrade` deletes, moves or overwrites a backup file. Conversion writes a
  new file beside the original and leaves the original alone. There is no flag anywhere that
  changes this, and a test asserts the command's source contains no destructive call.
- A backup that cannot be read forward stops the command rather than being skipped. The
  message offers the safe option first — install the version that wrote it in a separate
  environment and restore from there — because giving up a backup is rarely actually
  necessary. Accepting the loss requires an interactive terminal and an exact typed phrase
  naming how many backups are involved; there is no flag, no environment variable and no
  piped-input path, so nothing running unattended can reach it. Even then the files stay on
  disk.
- The instructions shipped for AI assistants forbid confirming that step at all: an
  assistant that meets an unconvertible backup must stop and tell the developer.

### Changed

- The README is rewritten around what a developer does rather than what the library
  contains: a five-minute quick start that ends in a working backup, then the panel, the
  schedule, off-site copies, restoring, and the client — each leading with the shortest
  snippet that works. It gains a troubleshooting section keyed to the errors DBS actually
  emits, and an *Upgrading* section that leads with the command and documents what happens
  to old backups.
- The instructions shipped for AI assistants gain the setup and upgrade requirements, a
  troubleshooting map, a note that the guard does nothing unless `DBSSecurityMiddleware` is
  installed, and an instruction to run `dbs upgrade --check` before other work. The settings
  and command references were regenerated against the code.
- The admin wiki gains an *Upgrading* page.
- `SECURITY.md` states that the guard is inert without its middleware.
- `CLAUDE.md` records the rule that keeps this honest: a change requiring developer action
  is not finished until `dbs/upgrade.py` has a step for it, and a container format bump must
  keep `MAGIC` stable and register its converter in the same commit.

## [0.3.0] - 2026-09-02

### Added

- A control panel inside the Django admin at `/admin/dbs/`, mounted automatically
  when `dbs` sits in `INSTALLED_APPS` alongside `django.contrib.admin`. No URLconf
  change. It wears the admin's own theme and covers a dashboard, taking a backup
  (downloaded or pushed to a target), restoring an uploaded file with a dry run,
  managing SFTP targets, a per-target SSH console, and a built-in wiki. Superusers
  only; there is no grantable permission for it.
- SFTP targets are database rows now, not only the `DBS_SSH_TARGETS` setting.
  Passwords, pasted private keys and key passphrases are encrypted at rest with
  AES-256-GCM under a key derived from `SECRET_KEY`, are never re-displayed, and are
  read through `SECRET_KEY_FALLBACKS` so a rotation does not orphan them. Targets
  defined in settings keep working and appear read-only.
- A session guard for the panel. A first-login wizard asks which networks you use and
  how strict to be; after that every admin request is scored by an
  `IsolationForest` and by rules for an unseen network prefix, an unseen browser,
  implied travel speed, and destructive actions from unrecognised networks. A warning
  score asks for re-authentication; a blocking score ends every session for that
  account, records an `AnomalyEvent` and can email. Requests from
  `DBS_TRUSTED_NETWORKS` and accounts inside the learning period are scored and
  recorded but never enforced against.
- The anomaly model ships pre-trained. `dbs/security/baseline.json.gz` holds a
  synthetic corpus of normal admin behaviour, regenerated by
  `scripts/train_base_model.py`, so scoring works from the first request instead of
  starting blind. Once an account passes `DBS_ANOMALY_MIN_ROWS` events a personal
  forest is fitted on its own history mixed with a shrinking sample of that corpus.
  Nothing is ever pickled or unpickled: models are refit from stored feature rows,
  because deserialising an estimator out of the database this feature protects would
  be a remote-code-execution hole in the security layer.
- An authorization endpoint the open admin page polls every few seconds, so
  deactivating an account, dropping its superuser flag, or a blocking score takes
  effect in a live tab rather than at the next navigation. Enforcement itself is
  server-side in `DBSSecurityMiddleware`; the poll is a convenience, never the
  boundary.
- Optional browser geolocation as an anomaly signal, off unless
  `DBS_GEOLOCATION = True` and the developer opts in during setup. It contributes
  distance from a known location and implied travel speed. Coordinates are rounded to
  about a kilometre before storage. A location can only ever raise a risk score, never
  lower one — it comes from the client and can be forged — and an absent or declined
  fix is neutral rather than suspicious.
- One command: `manage.py dbs backup|restore|validate|schedule|key|security|ai`.
  `manage.py django-dbs` runs the same command under its old name and points at the
  shorter one. The original `dbs_backup`, `dbs_restore`, `dbs_validate` and
  `dbs_schedule` commands are unchanged and are not deprecated.
- `manage.py dbs key` reports where the backup passphrase comes from and prints it
  with `--show`, so it can be archived before a `SECRET_KEY` rotation.
- `manage.py dbs security` with `status`, `unlock`, `policy`, `retrain`,
  `reset-baseline`, `events` and `purge`. `unlock` is the escape hatch: shell access
  always beats the detector.
- Instructions that teach an AI coding assistant how to use DBS, shipped inside the
  package under `dbs/ai/` and installed into a project by `manage.py dbs ai`, which
  writes `.claude/skills/django-dbs/`, appends to `AGENTS.md` with `--agents`, and
  reports drift with `--check` for CI.
- Settings: `DBS_PASSPHRASE`, `DBS_ADMIN_CONSOLE_SHELL`, `DBS_ANOMALY_ENFORCE`,
  `DBS_ANOMALY_DETECTOR`, `DBS_ANOMALY_MIN_ROWS`, `DBS_TRUSTED_NETWORKS`,
  `DBS_GUARD_POLL_SECONDS`, `DBS_GUARD_EVERYWHERE`, `DBS_GEOLOCATION`,
  `DBS_SECURITY_RETENTION_DAYS`, `DBS_SETUP_WIZARD`, `DBS_TRUST_FORWARDED_FOR`,
  `DBS_TRUSTED_PROXIES`.
- Failed admin logins are recorded as audit events and feed the detector's
  `recent_failures` signal.
- `expected_networks` from the setup wizard is used: a request from outside them adds risk.
- The learning period counts distinct sessions rather than requests, so the guard's own
  polling no longer burns through it in minutes.
- `DBS_GUARD_EVERYWHERE` extends the authorization poller to the rest of the admin.

### Security

- A session can no longer vouch for its own novelty. "Seen" network prefixes and browsers
  are drawn only from a user's *other* sessions, so one extra request can no longer clear
  the new-network and new-browser signals for the rest of a hijacked session.
- A `warn` verdict is enforced rather than merely displayed: the middleware refuses any
  non-read action from a flagged session until it authenticates again.
- A lockout is checked on every authenticated superuser request, not only inside the panel,
  so it bites whatever the session backend and wherever the request lands.
- `BackupRecord.location` is read-only and downloads resolve only inside `DBS_BACKUP_DIR`.
  The catalogue is not a file browser.
- Trusted networks are limited to /8 or narrower (v4) and /16 or narrower (v6), in the form
  and again when they are read, so a guarded session cannot trust the whole internet.
  Malformed networks and notification addresses are now rejected with an error instead of
  being silently dropped.
- Audit fields are clamped to their column widths and the console's audit label is chosen by
  the server, so an action can no longer execute without leaving an accurate record.
- `DBS_TRUSTED_PROXIES` counts the client address from the right-hand end of
  `X-Forwarded-For`, where an appending proxy puts it.

### Changed

- The backup passphrase is derived from Django's `SECRET_KEY` when nothing else
  supplies one, so a new install needs no passphrase configuration at all. The
  derivation is domain separated, so the backup key is never the same bytes Django
  uses for sessions, CSRF and password-reset tokens. Restore and validate also try
  keys derived from `SECRET_KEY_FALLBACKS`. Explicit options, `$DBS_PASSPHRASE` and
  the `DBS_PASSPHRASE` setting still take precedence, in that order.
- `dbs_schedule` no longer refuses to start without `$DBS_PASSPHRASE`; it derives one
  from `SECRET_KEY` instead. It still refuses when neither is available.
- `dbs_backup` reports which source the passphrase came from.
- `DEFAULT_EXCLUDES` now also skips DBS's own catalogue and telemetry tables
  (`dbs.backuprecord`, `dbs.auditevent`, `dbs.sessionevent`, `dbs.anomalyevent`,
  `dbs.lockout`). Restoring one project's backup history and audit trail over
  another's is never wanted. `dbs.backuptarget` and `dbs.securitypolicy` stay backed
  up, so a restore brings your configuration back.
- `scikit-learn` is a new hard dependency.

### Upgrading

**This release adds database models. Run `python manage.py migrate` after upgrading.**
Add `dbs.security.middleware.DBSSecurityMiddleware` to `MIDDLEWARE` to enable the
session guard; without it the panel still works and is still superuser-only, but
nothing is scored or enforced. The first superuser to open the admin is redirected
once to the setup wizard, which `DBS_SETUP_WIZARD = False` disables.

## [0.2.2] - 2026-08-14

### Added

- `restore_backup` accepts `dry_run`, surfaced as `dbs_restore --dry-run`. It
  runs the real load inside a transaction it rolls back and writes no files, so
  a restore can be rehearsed against the target it will actually run on.
- `restore_backup` accepts `flush`, surfaced as `dbs_restore --flush`. It clears
  the backed-up models — auto-created many-to-many tables included, children
  first — in the same transaction as the load, so the restore replaces rather
  than merges and a failure leaves the database untouched.
- A restore onto a database that already holds rows for the backed-up models
  logs a warning naming them. Merging stays the default; the warning makes the
  blend visible instead of silent.
- Backups record the applied migration per app, and a restore compares that
  against the target and warns when the two have drifted, naming the apps and
  the direction. Rows for models and fields the target does not know are
  discarded on load, so this makes a previously silent loss visible. Backups
  written before this release carry no migration state and restore unchanged.
- `RestoreResult` reports `records_would_load`, `files_would_write`,
  `records_flushed` and `preexisting_models`.
- The test suite runs against PostgreSQL with `DBS_TEST_DB=postgres`, and CI
  exercises it on every push. Sequence handling is backend specific and was not
  observable on SQLite.

### Fixed

- Restoring rows that carry explicit primary keys now resets the database
  sequences afterwards, the way `loaddata` does. Without it, every sequence on
  PostgreSQL stayed at its starting value while the restored rows occupied much
  higher primary keys, so the first row a project created after a restore failed
  with a duplicate key error. A restore of a seven-user database left every
  sequence at 1.
- A container truncated so that the second payload copy is short or missing now
  restores from the surviving first copy instead of being refused outright.
  Truncation is the most common way a stored file degrades, and the second copy
  occupies the whole tail of the container, so this was the one case redundancy
  most needed to cover. A file truncated into the first copy still raises
  `ContainerError`, and `RepairReport` reports the recovery through its new
  `copies_available` field rather than presenting it as an untouched read.

### Changed

- `DBS_EXCLUDE_MODELS` now extends the default exclusions
  (`contenttypes.contenttype`, `auth.permission`, `admin.logentry`,
  `sessions.session`) instead of replacing them. Previously, listing a single
  custom model silently re-enabled backup of all four defaults — models that
  are rebuilt by migrations on the restore target, where restoring stale rows
  corrupts generic relations and permission grants. A developer who
  deliberately wants to back up a default-excluded model prefixes its label
  with `-`, e.g. `DBS_EXCLUDE_MODELS = ["-sessions.Session"]`. Projects that
  relied on the old replacement behaviour must switch to the `-` prefix.
- The restore-semantics documentation no longer describes a backup as a
  consistent snapshot taken while the application keeps writing. Collection runs
  in a transaction, but where the connection's isolation level is READ COMMITTED
  each statement takes its own snapshot, so a backup spanning many models can
  read some of them before a concurrent change and others after it. The README
  now states that and how to avoid it.

## [0.2.1] - 2026-07-31

### Added

- Django 6.0 and Python 3.13 support: the dependency range widens to
  `Django>=4.2,<7`, and CI runs the suite on Python 3.13 with Django 6.0.
- README: a "Signals during restore" section. Restore saves rows with
  `raw=True` the way `loaddata` does; receivers that run business side
  effects must return early on raw saves or a restore replays them against
  a half-loaded database.

### Fixed

- README showed a `-p` short flag on `dbs_validate` that the command never
  had; the example now uses `--passphrase`.

## [0.2.0] - 2026-07-29

### Added

- A standalone `dbs-client` command, installed by the new `[client]` extra. It
  connects to a server running django-dbs over SSH, triggers a backup there and
  downloads it, all on one connection. Subcommands: `init`, `test-connection`,
  `list`, `backup`, `pull`, `push`, `prune`, `schedule`, `validate`. It is
  configured by a TOML file discovered from `--config`, `$DBS_CLIENT_CONFIG`,
  `./dbs-client.toml` or `~/.config/dbs/client.toml`, and runs with no Django
  settings configured.
- `manage.py dbs_schedule`: unattended backups on a repeating interval with
  local retention and an optional push to a `DBS_SSH_TARGETS` entry plus remote
  retention. `--once` runs a single cycle. `SIGTERM` and `SIGINT` end the loop
  immediately, and a failing cycle is logged without stopping the schedule.
- SSH targets accept every authentication route: a `.pem` or OpenSSH key file,
  an encrypted key with `key_passphrase`, a password, or ssh-agent. Any secret
  may be read from an environment variable with a `_env` suffixed key. `~` is
  expanded in `key_filename` and `known_hosts`, and `connect_timeout` bounds the
  handshake.
- `--passphrase-stdin` on `dbs_backup` and `dbs_restore`, reading the passphrase
  from the first line of standard input so it never appears in argv.
- Transport additions: `SSHSession` and `open_session` for reusing one
  connection, `pull_backup_to` for streaming a download straight to disk,
  `list_backup_details`, `delete_backup` and `check_connection`.
- A shared backup filename convention (`prefix-YYYYMMDD-HHMMSSZ.dbs`, UTC) and
  retention helpers that only ever consider names matching that convention and
  the configured prefix, and that refuse to keep fewer than one backup.
- Settings: `DBS_BACKUP_DIR`, `DBS_BACKUP_PREFIX`, `DBS_SCHEDULE_INTERVAL`,
  `DBS_SCHEDULE_KEEP`, `DBS_SCHEDULE_PUSH_TARGET`, `DBS_SCHEDULE_KEEP_REMOTE`.
- Logging throughout under the `dbs` logger: backup/restore start and finish,
  healed-corruption warnings, skipped files, SFTP transfers, scheduled cycles
  and retention.
- Settings: `DBS_RESTORE_ROOTS`, `DBS_MAX_UPLOAD_BYTES`,
  `DBS_MAX_PAYLOAD_BYTES`, `DBS_KDF_TIME_COST`, `DBS_KDF_MEMORY_COST`,
  `DBS_KDF_PARALLELISM`.
- CI workflow running lint and the test suite across Python 3.9–3.12 and
  Django 4.2/5.x on every push and pull request.
- `SECURITY.md` with a private vulnerability reporting channel.

### Changed

- `paramiko` is imported lazily, so `dbs.transports` can be imported and SSH
  targets parsed without the optional extra installed.
- Uploads and downloads land atomically: bytes go to a `.part` file that is
  renamed into place only once the transfer completes.
- `list_backups` returns only files matching the backup filename convention;
  pass `pattern_only=False` for the previous behaviour.
- The admin download filename now uses the shared convention in UTC rather than
  the server's local time.
- Unknown keys in an SSH target or a client config are rejected instead of
  ignored, so a typo cannot silently disable host key checking.
- Settings are read through a helper that tolerates unconfigured Django, so
  validating a backup no longer requires a Django project.
- `dbs.engine` resolves its members lazily, matching `dbs`.
- Restoring `path`/`root` file entries now requires configuring
  `DBS_RESTORE_ROOTS` (or `DBS_FILE_ROOTS`); unconfigured projects restoring
  such entries will get a `RestoreError` until a root is allow-listed.
- Django dependency is capped below 6.

### Security

- The backup passphrase is never passed as a command-line argument. When the
  client triggers a backup it is written to the remote process over the
  encrypted SSH channel's standard input, appearing in neither the remote
  argv nor the remote environment. A legacy `passphrase_transport = "env"` mode
  is available for servers still on 0.1.x and is documented as the weaker option.
- `dbs_schedule` reads the passphrase only from `$DBS_PASSPHRASE` and refuses to
  start without it, rather than blocking on a prompt no operator can see.
- A client config holding a literal secret must not be readable by other users,
  and a config writable by other users is refused regardless of its contents.

- Restored files are now confined to allow-listed directories. `path` and
  `root` file entries are only written when the resolved target lies under a
  directory in `DBS_RESTORE_ROOTS` (falling back to `DBS_FILE_ROOTS`);
  anything else raises `RestoreError`. This closes an arbitrary-file-write
  path where a crafted backup could write outside the project.
- Argon2 parameters read from a backup manifest are validated against upper
  bounds before any key derivation, preventing memory-exhaustion from crafted
  containers.
- The admin pages render messages through Django template context with
  autoescaping instead of interpolating text into template source, removing a
  template-injection/XSS vector in error messages.
- The admin restore view rejects uploads larger than
  `DBS_MAX_UPLOAD_BYTES` (default 1 GiB), and decompression on restore is
  bounded by `DBS_MAX_PAYLOAD_BYTES` (default 4 GiB).
- `--passphrase` help text now warns that command-line arguments are visible
  to other local processes.

### Reliability

- Database restore now runs inside a single transaction: a failure anywhere
  during row loading or the final constraint check rolls back everything.
- Backup collection runs inside a transaction for a consistent snapshot of
  all models.
- Writing a backup to disk is atomic and durable: bytes go to a temporary
  file, are fsynced, then renamed over the target; verify-after-write now
  re-reads the on-disk bytes.
- File restores to disk are atomic (write-temp-then-rename), and storage-field
  restores keep a safety copy until the new content is fully saved.
- Source files that cannot be read during backup are no longer silently
  skipped: they are recorded in the manifest stats (`skipped_files`) and
  logged as warnings.
- Containers and manifests with an unknown format version are rejected with a
  clear error instead of being misparsed.

## [0.1.4] - 2026-07

- Tagged from the security, reliability and operations hardening work; every
  entry it carried is listed under 0.2.0 above.

## [0.1.3] - 2026-07

- Bilingual end-to-end stress test for backup, delete and restore.

## [0.1.2] - 2026-07

- Release-tag check reads from the release event payload.

## [0.1.1] - 2026-07

- Project notice and memory; publish workflow tidy-up.

## [0.1.0] - 2026-07

- Initial release: encrypted, redundant, self-healing single-file backup for
  Django models, relations and files; CLI commands, admin UI, SFTP transport.
