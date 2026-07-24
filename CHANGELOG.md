# Changelog

All notable changes to this project are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - Unreleased

### Security

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

### Added

- Logging throughout under the `dbs` logger: backup/restore start and finish,
  healed-corruption warnings, skipped files, and SFTP transfers.
- Settings: `DBS_RESTORE_ROOTS`, `DBS_MAX_UPLOAD_BYTES`,
  `DBS_MAX_PAYLOAD_BYTES`, `DBS_KDF_TIME_COST`, `DBS_KDF_MEMORY_COST`,
  `DBS_KDF_PARALLELISM`.
- CI workflow running lint and the test suite across Python 3.9–3.12 and
  Django 4.2/5.x on every push and pull request.
- `SECURITY.md` with a private vulnerability reporting channel.

### Changed

- Restoring `path`/`root` file entries now requires configuring
  `DBS_RESTORE_ROOTS` (or `DBS_FILE_ROOTS`); unconfigured projects restoring
  such entries will get a `RestoreError` until a root is allow-listed.
- Django dependency is capped below 6.

## [0.1.3] - 2026-07

- Bilingual end-to-end stress test for backup, delete and restore.

## [0.1.2] - 2026-07

- Release-tag check reads from the release event payload.

## [0.1.1] - 2026-07

- Project notice and memory; publish workflow tidy-up.

## [0.1.0] - 2026-07

- Initial release: encrypted, redundant, self-healing single-file backup for
  Django models, relations and files; CLI commands, admin UI, SFTP transport.
