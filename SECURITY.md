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
- Passphrases are never passed as command-line arguments. Unattended runs read
  them from the environment (`DBS_PASSPHRASE`) or from a client config file that
  must not be readable by other users. When `dbs-client` triggers a backup on a
  server, the passphrase travels over the encrypted SSH channel's standard input
  and appears in neither the remote process's arguments nor its environment.
  The legacy `passphrase_transport = "env"` mode places it in the remote
  process's environment instead, which is readable by root and by the same user.
- Remote transfers verify host keys and reject unknown hosts by default. Setting
  `auto_add_host_key` trusts whatever key a server first presents.

## The admin control panel

The panel at `/admin/dbs/` can download and overwrite the whole database. It is
restricted to superusers, and there is deliberately no grantable permission for it.

Credentials for SFTP targets are encrypted at rest with AES-256-GCM under a key
derived from `SECRET_KEY` by HKDF-SHA256, and are never re-displayed. They live in the
database, which means they are inside any backup taken of that database; those
containers are themselves encrypted.

`DBS_ADMIN_CONSOLE_SHELL` is off by default. Turning it on gives every superuser
arbitrary command execution on the target server from a browser.

## The session guard

The guard runs only when `dbs.security.middleware.DBSSecurityMiddleware` is in
`MIDDLEWARE`. Without it the panel is still superuser-only, but nothing is scored and
nothing is enforced.

Every admin request is scored and the outcome is enforced server-side in
`DBSSecurityMiddleware`. The polling endpoint an open page uses is a convenience, not
the boundary. Browser geolocation, when enabled, is client-supplied and therefore may
only raise a risk score, never lower one.

Anomaly models are always refit from stored feature rows. DBS never pickles or
unpickles an estimator.

If the guard locks out the only superuser, recovery is from a shell:
`python manage.py dbs security unlock USERNAME`.

## What the panel does not defend against

A superuser is trusted with the database by definition, so the guard raises the cost of a
*hijacked* session rather than constraining a legitimate one. In particular:

- A superuser who edits a password-authenticated SFTP target to point at a host they control
  and then runs the connection check will receive that password. This is inherent to
  password authentication; prefer a key file.
- `DBS_TRUST_FORWARDED_FOR` puts the client IP under the control of whatever sets that
  header. Enable it only behind a proxy you control, and set `DBS_TRUSTED_PROXIES` to the
  number of hops so the address is read from the correct end.
- Sessions held in a cache or signed-cookie backend cannot be deleted server-side. A lockout
  is checked on every request instead, so such a session stops at its next request rather
  than instantly.
