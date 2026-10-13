# DBS 0.7.0 — release notes

Released 2026-10-13.

```bash
pip install --upgrade "django-dbs[guard]"   # name the extras you use: guard, manager, ssh or all
python manage.py dbs upgrade
```

Backups now stream: a multi-threaded engine writes container format 2 with flat memory however
large the project, and restores read it the same way. The server keeps its backups and the DBS
manager pulls them, so the panel's SFTP targets and console are gone, and so is `dbs-client`.
`pip install django-dbs` is the backup library alone; the session guard's detector, the manager
and the SSH API are extras. The manager gains roles, a master account, two-factor sign-in and a
sealing key in the system keychain, can revert a move to a new server, and asks for a person
before Claude pins a host key. A long list of backup, restore and retention fixes closes ways a
backup or a restore could lose data.

The full list of changes is in the
[changelog](https://github.com/bn7ya/dbs/blob/main/CHANGELOG.md#070---2026-10-13).

## Highlights

### Backups stream

Rows are read in batches from one database snapshot and files in chunks, while a compression
pool, an encoding thread and a writer thread work behind bounded queues, so memory stays flat
however large the project grows. A failure in any stage stops them all and never leaves a
partial file.

```python
from dbs import write_backup

summary = write_backup("backup.dbs", "passphrase")   # a path that does not exist yet, or a binary file
print(summary.bytes_written, summary.sha256, summary.records, summary.skipped_files)
```

`write_backup` and `BackupSummary` are new in `dbs`. `workers` spreads parity and encryption
over more threads. `restore_backup` and `validate_backup` take bytes, a path or a seekable file
and read format 2 as a stream. Reed-Solomon parity is computed with numpy and an intact block is
read without decoding: format 1 encoding goes from about 0.4 to 53 MB/s and a clean validation
from 0.3 to 112 MB/s.

### Container format 2

New backups write both copies of every block, the second 64 blocks after the first, so a burst
of damage never reaches both. Each block is one AES-256-GCM chunk authenticated together with
the header, with Reed-Solomon parity and a keyed BLAKE2b tag; the header and the trailer are each
written twice with a checksum, and no plain hash of the data is stored. A reordered, swapped or
truncated block is detected through its authenticated position.

Format 1 backups still validate and restore. `python manage.py dbs upgrade --backups DIR`
converts them into `<name>.v2.dbs` beside the original, validated before it takes the name, and
leaves the original alone.

### A backup on standard output

```bash
python manage.py dbs backup --stream > /mnt/elsewhere/backup.dbs
```

`--stream` writes the backup to standard output and keeps the same bytes in `DBS_BACKUP_DIR`
(or `--output-dir`) under the usual name for `--prefix`. Messages go to standard error, whose
last line is a JSON summary `{"name", "size", "sha256"}`. When standard output breaks mid-way,
the backup still finishes on the server, the command exits 0 and the summary adds
`"kept_on_server": true`. This is how the DBS manager takes a backup.

### The server keeps its backups; the manager pulls them

The panel no longer pushes anything. It keeps at most five backups in `DBS_BACKUP_DIR`, never
prunes the newest verified one, and holds no server credential. Every DBS backup run in the
manager:

1. **collects** the backups waiting on the server under its server's or plan's name;
2. **streams** a fresh one with `dbs backup --stream`;
3. **verifies** each: the size and SHA-256 the server reported, then a full decryption;
4. **removes** the server's copies it recorded and verified, keeping `keep_remote` (0 to 5).

A broken stream ends as *kept on the server*, not failed, and the next run collects it. A file
that fails verification is quarantined as `NAME.quarantined` with the reason, never restored and
never counted. The manager keeps at most five good backups per server and plan and never deletes
the newest one that passed verification.

### One install for each machine

| Install | Adds |
|---|---|
| `pip install django-dbs` | The backup library: Django, cryptography, argon2-cffi, reedsolo and numpy |
| `"django-dbs[guard]"` | scikit-learn, for the session guard's anomaly detector |
| `"django-dbs[manager]"` | djangorestframework, waitress, paramiko and keyring, for `django_dbs` |
| `"django-dbs[ssh]"` | paramiko, for `dbs.transports` |
| `"django-dbs[all]"` | All three |

Every dependency is capped below its next major version. A missing extra is reported with the
`pip install` line that fixes it: `django_dbs` without the manager extra prints it and exits 1,
and `manage.py dbs upgrade` reports a session guard that is on without scikit-learn.

### A guarded manager

- **Roles.** Every account is a master, an admin, an operator or a viewer, checked in every
  service, so the interface, the REST API, the terminal and the MCP server share one rule.
  Rehearsals need an operator; real restores and moves need an admin.
- **The master account** is the one made at setup (on upgrade, the oldest account; every other
  becomes an admin). Only it manages accounts, on the **Accounts** page or with
  `django_dbs createuser NAME --role ROLE` and `django_dbs account list|role|disable|enable|reset-2fa`.
- **Two-factor sign-in.** Every web sign-in takes the password and then a code from an
  authenticator app, or one of ten single-use recovery codes. An account enrolls at its next
  sign-in with a QR code.
- **Passwords last 30 days** for web sign-in. New accounts choose their own at their first
  sign-in.
- **The sealing key in the system keychain**, through keyring, wherever one works;
  `DBS_MANAGER_KEY_STORE=file|keychain` chooses. The manager warns when the key sits in a file
  next to the data and refuses to start when the keychain and a key file disagree.
- **Behind a TLS proxy.** `django_dbs run --trusted-proxy CIDR` believes the forwarded scheme
  and client only from the proxy's range, with `Secure` cookies and HSTS. A non-loopback
  `--host` is refused without it unless `--allow-insecure-http` accepts the risk.
- **Connection liveness.** Each server shows whether it is online and when it was last seen.
  Sessions send a keepalive every 15 seconds, and where a server has `timeout`, every remote
  command runs under a deadline.

### Moving to a new server, and back

A move backs up the old server now when it answers, records the new server's `.env`, takes a
safety backup of the new server's data, then pushes the `.env`, migrates, restores and checks.
A move that stops after changing the new server names the step and can be reverted: the
recorded `.env` goes back and the safety backup is restored.

```bash
django_dbs redeploy start --from old --to new --real
django_dbs redeploy revert 412 --real      # 412: the move's activity number
```

### Host keys a person confirms

The MCP `fingerprint_host` tool holds the key it read for ten minutes and returns a
confirmation id. `add_server` pins it only after a person confirms it on the Servers page or
with `django_dbs server confirm-host-key ID` at a real terminal.

## Backup and restore fixes

- **A dry run could change sequences.** It now never touches one, and a real restore only
  raises a PostgreSQL sequence, never below its current value.
- **A merge restore overwrote fields the backup did not carry**, so `FieldType.EXCLUDE` fields
  lost their values. A merge now updates only the fields a backup carries.
- **`--flush` deleted every row of a model**, even when `ModelBackup.get_queryset` backed up
  only some of them. It now deletes only the rows the backup covers.
- **On MySQL, `--flush` stopped with a foreign key error** whenever a row the backup does not
  cover pointed at one it replaces. It now works as on PostgreSQL and SQLite, and refuses a
  restore that would leave a link to a row it removed.
- **`--database` was not honoured**: a backup read rows, files and lookups from the default
  database.
- **A backup could replace an existing file.** `dbs backup PATH` and
  `create_backup(output=PATH)` now refuse a path that exists, write beside it, verify and only
  then link the file into place.
- **A missing source file was skipped without a word**, and a FIFO in a file tree could hang a
  backup. A missing or unreadable file now stops the backup and names it;
  `--allow-missing-files` backs up without it and lists it. Only regular files are read.
- **Files were written before the rows committed**, and stayed when the load failed. Every file
  target is checked before any row loads, and files move into place when the rows commit.
- Restores load models in the order the backup recorded, parents first, and a multi-table child
  brings its parent rows.
- **One damaged byte in a header could hide a backup.** Only a header copy that verifies is
  used.
- **Retention could prune the newest good backup**, ordered backups by name alone, and let two
  backups in one second overwrite each other.
- Panel backups and restores ran inside the web request; they now run as background jobs, one
  at a time, on a page that follows them.
- A scheduled backup took a six-hour lease, so a killed run blocked the schedule for hours. It
  now holds a two-minute lease renewed every 30 seconds and retries a killed run once.

## Upgrading from 0.6.x

Install the extras you use, then run `python manage.py dbs upgrade`. It applies the migration
that seals the audit trail and drops the SFTP targets, and reports each of these. The README's
[Upgrading](https://github.com/bn7ya/dbs#upgrading) section has the full table.

- **Off-site copies.** `DBS_SSH_TARGETS`, `DBS_SCHEDULE_PUSH_TARGET`,
  `DBS_SCHEDULE_KEEP_REMOTE` and `DBS_ADMIN_CONSOLE_SHELL` do nothing; delete them and add the
  server to a DBS manager, which pulls its backups. The audit trail names every SFTP target the
  panel held, without credentials.
- **`dbs-client` is gone.** Install the manager on your own machine and add each server from
  the old config with `django_dbs server add`.
- **Retention.** A schedule keeping more than five backups is lowered to 5. `dbs schedule`
  refuses a `DBS_SCHEDULE_KEEP` above 5, and the panel reads one as 5.
- **`DBS_TRUSTED_PROXIES`** lists proxy networks now, not a count:
  `DBS_TRUSTED_PROXIES = ["10.0.0.0/24"]`.
- **Key derivation limits.** A `DBS_KDF_TIME_COST` above 10 or `DBS_KDF_MEMORY_COST` above
  262144 KiB makes every backup fail; lower them.
- **Unmanaged models** (`managed = False`) are left out of backups unless registered or listed
  as `-app.model` in `DBS_EXCLUDE_MODELS`.
- **Backup paths.** A script that reuses one `dbs backup PATH` must choose a new path each run.
- **The manager migrates itself** the next time any `django_dbs` command starts: its oldest
  account becomes the master and every other one an admin, each account sets up two-factor
  sign-in at its next web sign-in, and plans keep 1 to 5 backups here and 0 to 5 on the server.
- **Every server the manager backs up needs django-dbs 0.7 or later.** An older one answers
  `dbs_too_old` and names the version it needs.
- `django_dbs redeploy start` no longer takes `--archive` or `--migrate`.

## Removed

- `dbs-client`, `python -m dbs.client`, the `dbs.client` API, the `client` extra and
  `django_dbs server import-profiles`.
- The panel's SFTP targets, its push option, its console with fixed actions and a free-form
  shell, and `dbs schedule --push` / `--keep-remote`.
- The panel's *download to my browser* option, which built a backup inside the request.
- The move's folder-archive step.

## Security

- `X-Forwarded-For` is read only from a request whose peer is in `DBS_TRUSTED_PROXIES`, and an
  address the guard cannot read counts as a new network.
- A flagged session is refused every change anywhere in the admin, and every download or
  export, the contrib views included.
- Learning mode mutes only the anomaly model; the rules and both thresholds apply from the
  first request.
- The audit trail is sealed in a hash chain; `python manage.py dbs audit verify` prints the
  first broken link, or the head of the chain to keep elsewhere.
- Telemetry stores the network and a keyed hash of the address instead of the address, and is
  purged after `DBS_SECURITY_RETENTION_DAYS`.
- Every local backup file and every temporary file it is written through is readable by its
  owner alone from the first byte; an SFTP upload is too, before its bytes arrive.
- The console, which could run free-form commands on remote servers from a browser, is gone.
- Claude can no longer pin a host key no person confirmed, make a plan keep fewer backups, or
  save a file the manager keeps encrypted.

[SECURITY.md](https://github.com/bn7ya/dbs/blob/main/SECURITY.md) names the supported versions,
how to report a vulnerability, the timelines, the scope and the threat model.

## Licenses

DBS is MIT.
[THIRD_PARTY_LICENSES.md](https://github.com/bn7ya/dbs/blob/main/THIRD_PARTY_LICENSES.md) names
the license of every dependency, of what the manager's interface bundles, and of the development
tools. What changed in this release:

| Package | Now | License |
|---|---|---|
| numpy | required | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| scikit-learn | `guard` extra | BSD-3-Clause |
| paramiko | `ssh` and `manager` extras | LGPL-2.1-or-later |
| djangorestframework, waitress | `manager` extra | BSD-3-Clause, ZPL-2.1 |
| keyring | new, `manager` extra | MIT |
| qrcode-generator | new, bundled in the manager's interface | MIT |
| tomli | no longer installed | MIT |
