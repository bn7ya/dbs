# Security policy

## Supported versions

| Version | Security fixes |
|---|---|
| 0.6.x | Yes |
| 0.5.x and older | No |

Fixes ship as a new 0.6.x release on PyPI. Pin the fixed version in your requirements or lock
file and reinstall; inside a virtual environment `python manage.py dbs upgrade --self --to
VERSION` installs exactly that version and then `python manage.py dbs upgrade` finishes the
upgrade. Older lines receive no fixes, so the first step for any report against them is to
upgrade.

## Reporting a vulnerability

Please do not open a public issue, pull request or discussion for a security problem. Report it
privately, by either of these:

1. **GitHub private vulnerability reporting (preferred):**
   <https://github.com/bn7ya/dbs/security/advisories/new>. The report, the conversation and the
   fix stay private to you and the maintainers until the advisory is published.
2. **Email:** asas.tech.om@gmail.com, if you cannot use GitHub.

Please include:

- the affected version(s) of `django-dbs`, Python and Django;
- which part is affected: the backup library, the control panel, the session guard, the
  `dbs.transports` API, or the DBS manager (its web interface, its terminal or its MCP server);
- the steps to reproduce it, ideally a minimal project or script;
- what an attacker gains, and what they need first (an account, a network position, a file).

Never send a real backup, a real passphrase or a real server credential. A backup made from a
throwaway database with a throwaway passphrase shows the same thing.

## What happens next

| Step | When |
|---|---|
| We acknowledge the report | within 3 working days |
| We confirm or rule out the issue and agree a severity with you | within 10 working days |
| A fixed release for a critical or high-severity issue | within 30 days of confirming it |
| A fixed release for a moderate or low-severity issue | within 90 days of confirming it |
| An update on progress | at least every 14 days until the fix ships |

Disclosure is coordinated. When the fixed release is on PyPI we publish a GitHub security
advisory, request a CVE through GitHub where one applies, and credit you unless you would rather
not be named. We ask you to keep the details private until then, or for 90 days from your
report, whichever comes first; if a fix needs longer we will say why and agree a new date with
you. If an issue is being exploited in the wild we may publish sooner, and will tell you first.

## Scope

In scope:

- **The backup library**: the container format, the encryption and key derivation, the
  Reed-Solomon repair, validation, restores, and every `manage.py dbs` command, including
  `dbs upgrade` and its handling of backups in an older format.
- **The control panel** at `/admin/dbs/` and **the session guard**
  (`dbs.security.middleware.DBSSecurityMiddleware`), including `dbs security unlock`.
- **The `dbs.transports` SSH and SFTP API.**
- **The DBS manager**: `django_dbs run` and its web interface and REST API, its terminal
  commands (`django_dbs server`, `backup`, `plan`, `activity`, `env`, `files`, `redeploy`), and
  its MCP server (`django_dbs mcp`). The manager holds the SSH credentials for every server it
  manages, so anything that exposes them, or lets someone act with them without signing in, is
  treated as critical.
- **What we publish**: the wheel and sdist on PyPI, and the workflows that build them.

Out of scope:

- A flaw in a dependency itself. Please report it to that project; tell us too if DBS uses it in
  a way that makes the flaw reachable.
- What a role is trusted to do by design: a superuser of the host project downloading or
  restoring its database, or a signed-in manager account using the servers it manages.
- Anything that needs the backup passphrase, or the `SECRET_KEY` it is derived from, first.
- Load against a deployment you do not own, and social engineering.

## Threat model

### Backups

- A backup is encrypted with AES-256-GCM under a key derived from the passphrase with Argon2id.
  Neither the passphrase nor the raw key is stored. Unless `DBS_PASSPHRASE` is set, the
  passphrase is derived from `SECRET_KEY`, so anyone with `SECRET_KEY` can read the project's
  backups; set `DBS_PASSPHRASE` to keep the two apart.
- Database statistics, model labels, file names and skipped-file paths stay inside the
  encrypted payload. The public manifest holds only what is needed to derive a key,
  authenticate, and repair the container.
- Every backup stores two copies plus Reed-Solomon parity. Damage is detected by the block
  hashes and the GCM tag, and repaired where the copies and the parity allow; a file altered by
  someone without the passphrase fails authentication rather than restoring altered data.
- KDF parameters read from a backup are bounded before any key derivation, so a crafted file
  cannot exhaust memory or time.
- Restores write files only inside `DBS_RESTORE_ROOTS` (falling back to `DBS_FILE_ROOTS`) and
  refuse every other path. Treat backup files and their passphrases as sensitive: a restore
  replaces the database.
- Nothing in DBS deletes or overwrites a backup when it upgrades one: `dbs upgrade --backups`
  writes each conversion under a new name, validates it, and leaves the original alone.

### File modes

On POSIX systems, every backup file DBS writes to a local disk is created with mode `0600`
(read and write for its owner only), and so is every temporary file it is written through,
from the first byte:

- backups written by `manage.py dbs backup`, by scheduled backups and by the API with an output
  path;
- conversions written by `dbs upgrade --backups`;
- backups pulled over SFTP by `dbs.transports`;
- backups, exports and imported files the DBS manager keeps in its data directory, whose
  folders it creates with mode `0700`.

A backup DBS uploads over SFTP is created on the server under a temporary name, set to `0600`
before its bytes are written, and then renamed into place.

DBS does not change the mode of a directory it did not create, such as `DBS_BACKUP_DIR` or an
SFTP target's folder, of a copy made by other software, or of a file a browser saves from the
panel or the manager. Those remain the operator's responsibility. On Windows, POSIX modes do
not apply and the folder's access control list decides who can read a backup.

### Passphrases and SSH

- Passphrases are never passed as command-line arguments. Unattended runs read them from
  `DBS_PASSPHRASE`, from the project's `SECRET_KEY`, or from a client profile file that must not
  be readable by other users.
- When the DBS manager, or the `dbs.client` API, runs a backup on a server, the commands are
  fixed argument lists and the passphrase travels on the SSH channel's standard input, so it
  appears in neither the remote process's arguments nor its environment. A client profile's
  legacy `passphrase_transport = "env"` puts it in the remote process's environment instead,
  where root and the same user can read it.
- Host keys are verified and unknown hosts are rejected by default. The manager pins each
  server's host key when the server is added; a changed key stops every connection until a
  person accepts the new one. `auto_add_host_key` trusts whatever key a server first presents.

## The admin control panel

The panel at `/admin/dbs/` can download and overwrite the whole database. It is restricted to
superusers, and there is deliberately no grantable permission for it.

Credentials for SFTP targets are encrypted at rest with AES-256-GCM under a key derived from
`SECRET_KEY` by HKDF-SHA256, and are never re-displayed. They live in the database, which means
they are inside any backup taken of that database; those containers are themselves encrypted.

`DBS_ADMIN_CONSOLE_SHELL` is off by default. Turning it on gives every superuser arbitrary
command execution on the target server from a browser. The console's named actions take no
command string from the browser.

## The session guard

The guard runs only when `dbs.security.middleware.DBSSecurityMiddleware` is in `MIDDLEWARE`.
Without it the panel is still superuser-only, but nothing is scored and nothing is enforced. Its
anomaly detector needs scikit-learn, which `pip install "django-dbs[guard]"` installs;
`manage.py dbs upgrade` reports a guard that is on without it.

Every admin request is scored and the outcome is enforced server-side in
`DBSSecurityMiddleware`. The polling endpoint an open page uses is a convenience, not the
boundary. Browser geolocation, when enabled, is client-supplied and therefore may only raise a
risk score, never lower one.

Anomaly models are always refit from stored feature rows. DBS never pickles or unpickles an
estimator.

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

## The DBS manager

The manager (`pip install "django-dbs[manager]"`, then `django_dbs run`) is a separate Django
project that reaches each server over SSH. It is never added to a host project's
`INSTALLED_APPS`, and the host project stores nothing about it.

- It holds the SSH keys and passwords of every server it manages, sealed with AES-256-GCM under
  a key derived from the manager's own secret key, and the backups it fetches, sealed the same
  way. `django_dbs paths` shows where each is kept. Anyone who can read both the data
  directory and that secret key can use those credentials, so keep the machine and the account
  that runs the manager to yourself. An export (`django_dbs export`) carries the credentials
  too, encrypted under the passphrase you give it; keep the file and that passphrase apart.
- It listens on `127.0.0.1` by default and warns when told to listen anywhere else. Prefer an
  SSH tunnel to exposing it. Sign-in is rate-limited per account and per address, and a session
  lasts eight hours.
- Its terminal commands run as whoever starts them, against the data directory they name; the
  operating system's file permissions are the boundary there.
- Its MCP server (`django_dbs mcp`) never accepts the account password and never returns a
  secret: no passphrase, private key, password or `.env` value. It offers no tool that restores
  or redeploys for real, removes or deletes anything, pushes a `.env`, or accepts a changed host
  key; restores and redeploys through it are always rehearsals, and anything that needs the
  account password is handed back to a person.
