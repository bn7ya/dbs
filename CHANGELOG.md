# Changelog

All notable changes to this project are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
