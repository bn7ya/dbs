# Security Policy

## Supported versions

Only the latest release of `django-dbs` receives security fixes.

## Reporting a vulnerability

Please do not open a public issue for security problems. Report them privately:

- Email: asas.tech.om@gmail.com
- Or use GitHub's private vulnerability reporting on this repository.

Include a description of the issue, steps to reproduce, and the affected
version. You should receive an acknowledgement within a few days; please allow
time for a fix and coordinated disclosure before publishing details.

## Scope notes for operators

- Backups are encrypted with AES-256-GCM under a key derived from the
  passphrase with Argon2id; the passphrase and raw data key are never stored.
- Restoring a backup writes files to disk. File writes are confined to the
  directories listed in `DBS_RESTORE_ROOTS` (falling back to
  `DBS_FILE_ROOTS`); restores refuse to write anywhere else. Treat backup
  files and their passphrases as sensitive.
- KDF parameters read from a backup are bounded before any key derivation to
  prevent resource-exhaustion attacks from crafted files.
