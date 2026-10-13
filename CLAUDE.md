# DBS — project memory

DBS (PyPI: `django-dbs`) is a Django backup library. It reads a project's models,
relations and files and writes one encrypted, redundant, self-healing file: every
backup stores two copies plus Reed-Solomon parity, so silent corruption is detected
and repaired on restore. Created by Sudum Technology — Research and Development sector.
This project is under active development; treat it as our very tiny contribution to
this world.

## Coding criteria

Follow these for every change:

- Write clean, maintainable, readable code. Let names carry the meaning.
- No comments. The only exception is a concise docstring on a developer-facing public
  API callable or class (the surface listed below).
- Always say "developer", never "end user".
- Never compare DBS to any other tool or solution — no benchmarks, no "unlike X", no
  feature tables ranking us against alternatives. Describe what DBS does on its own terms.

## Public API (the only place docstrings belong)

Re-exported from `dbs/__init__.py`:
`backup_registry`, `BackupRegistry`, `FieldType`, `ModelBackup`,
`create_backup`, `write_backup`, `BackupSummary`, `restore_backup`, `validate_backup`,
`default_passphrase`.

Re-exported from `dbs/transports/__init__.py`:
`SSHTarget`, `SSHSession`, `RemoteBackup`, `RemoteResult`, `open_session`,
`push_backup`, `pull_backup`, `pull_backup_to`, `list_backups`,
`list_backup_details`, `delete_backup`, `check_connection`, `fetch_host_key`,
`HostKey`, `HostKeyError`.

Everything else (internal functions, classes, modules) carries no docstring and no
inline comments. That includes `dbs/naming.py`, `dbs/retention.py`,
`dbs/scheduling.py`, `dbs/io.py`, `dbs/conf.py`, `dbs/keys.py`, `dbs/models.py`,
`dbs/admin.py`, `dbs/views.py`, `dbs/forms.py`, `dbs/files.py`, everything under
`dbs/security/`, `dbs/audit.py`, `dbs/leases.py`, `dbs/jobs.py`, `dbs/tee.py`,
`dbs/extras.py`, `dbs/upgrade.py`, `dbs/schedule_runner.py`, `dbs/health.py`,
`dbs/connection.py`, the internals of `dbs/engine/`, `dbs/container/` and `dbs/crypto/`
(`pipeline.py`, `frames.py`, `inputs.py`, `convert.py`, `stream.py`, `rs.py`,
`sources.py`, `chunked.py`) and everything under `dbs/manager/`.

## Layout

- `dbs/engine/` — backup, restore, validate and the format 1 to 2 converter. `pipeline.py`
  runs a backup through its threads (snapshot reads in the caller, a deflate pool, the
  encoder, the writer) behind bounded queues; `frames.py` and `payload.py` are the framed
  payload; `inputs.py` opens bytes, a path or a file for reading.
- `dbs/container/` — the on-disk format. `stream.py` is format 2 (`StreamWriter`,
  `StreamReader`, `FORMAT_VERSION`); `format.py` and `blocks.py` are format 1, still read;
  `rs.py` computes Reed-Solomon parity with numpy; `sources.py` reads a container from bytes
  or a file.
- `dbs/crypto/` — the Argon2id KDF with the bounds a read enforces, the AES-256-GCM envelope,
  and `chunked.py`, the per-block AES-256-GCM that format 2 uses.
- `dbs/transports/` — the SSH/SFTP API (`django-dbs[ssh]`): host-key-checked sessions,
  streamed remote commands, transfers through private partial files.
- `dbs/extras.py` — the one list of what each extra (`guard`, `manager`, `ssh`) must make
  importable; `tests/test_packaging.py` keeps it in step with `pyproject.toml`.
- `dbs/management/commands/` — the `dbs` umbrella and its `django_dbs` alias, plus
  `dbs_backup`, `dbs_restore`, `dbs_validate`, `dbs_schedule`, `dbs_connection`,
  `dbs_health`, `dbs_audit`, `dbs_key`, `dbs_security`, `dbs_ai`, `dbs_upgrade`.
- `dbs/contrib/` — the original standalone download/upload views, kept working.
- `dbs/models.py`, `dbs/admin.py`, `dbs/views.py`, `dbs/forms.py`,
  `dbs/templates/admin/dbs/`, `dbs/static/dbs/` — the control panel mounted at
  `/admin/dbs/`. Superusers only, enforced in `dbs/security/decorators.py` and in
  every `ModelAdmin`.
- `dbs/security/` — the session guard: feature extraction, the IsolationForest
  detector, the shipped base model, geolocation, verdicts, session termination, the
  middleware, trusted proxy networks (`networks.py`), telemetry retention
  (`telemetry.py`) and the system checks (`checks.py`).
- `dbs/ai/` — the instructions shipped for AI coding assistants, installed by
  `manage.py dbs ai`.
- `dbs/naming.py`, `dbs/retention.py`, `dbs/scheduling.py`, `dbs/io.py`,
  `dbs/conf.py` — Django-free helpers shared by the server and the manager: backup names,
  safe retention (at most five, the newest verified one always kept), intervals, files
  written privately and never over another.
- `dbs/audit.py`, `dbs/leases.py`, `dbs/jobs.py`, `dbs/schedule_runner.py`,
  `dbs/health.py`, `dbs/connection.py` — the sourceless, hash-chained audit trail, database
  leases, the runner lease and heartbeat every panel and scheduled job holds, the panel's
  schedule and its in-process runner, the health report, and the connection details the
  manager reads.
- `dbs/tee.py` — `dbs backup --stream`: standard output and a private partial file in the
  backup folder, linked into place under a backup name.
- `dbs/files.py` — the files a backup reads and a restore stages, checks and places, within
  the restore roots and `DBS_RESTORE_PATH_MAP`.
- `dbs/manager/` — the standalone DBS manager (`django_dbs run`, `django-dbs[manager]`): its
  own Django project (`dbs/manager/settings.py`), one app labelled `dbs_manager` with a
  subpackage per slice, the job runner and scheduler that replace Celery, and the built
  interface in `dbs/manager/static/dbs_manager/` (generated, not committed).
- `dbs/manager/permissions.py` — the one role policy: each capability names the least role
  (viewer, operator, admin, master) that may use it, and `@requires` on a service method
  enforces it for the REST views, the terminal and the MCP server alike.
- `dbs/manager/keystore.py` — the sealing key in the system keychain, or in the data folder
  where none works (`DBS_MANAGER_KEY_STORE`). `dbs/manager/staging.py` — `django_dbs import`
  built in a staging folder and swapped in, the old installation moved aside.
  `dbs/manager/recovery.py` — at start, interrupts jobs no live process runs and frees their
  locks.
- `dbs/manager/terminal/` — the manager's terminal commands (`django_dbs server|backup|plan|
  activity|env|files|redeploy`). Like the REST views, each verb validates with the slice's
  serializer and calls the slice's service; neither adapter holds business logic.
  `parsers.py` imports no Django, so `--help` stays instant.
- `dbs/manager/mcp/` — `django_dbs mcp`, the MCP server Claude drives: `protocol.py` is
  JSON-RPC over stdio with no Django, `tools.py` the tools, each calling a slice's service.
- `dbs/manager/adapters/` — the glue the terminal and MCP share: references by name or id,
  serializer validation, job results, the check summary, multi-server takes.
- `manager-ui/` — the manager's Angular source (Angular Material, Font Awesome Free).
  `scripts/build_manager_ui.sh` builds it into the package; `manager-ui/CLAUDE.md` holds
  its rules.
- `tests/` — pytest suite (pytest-django); `tests/fake_ssh.py` is the paramiko
  stand-in used by the transport and manager tests, and `tests/test_ssh_openssh.py` runs
  against a real OpenSSH server when `DBS_TEST_SSH_*` names one. `tests/manager/` is the
  manager's suite, run as a second session with its own settings.
- `promo/instagram-reel/` — the promotional reel: an HTML composition rendered frame by frame,
  a numpy soundtrack, and `build.sh` that makes the MP4. Its README traces every on-screen claim
  to a run or a line of the README; not part of the package.
- `RELEASE_NOTES.md` — the developer-facing notes for the current release, used as the GitHub
  Release body. `THIRD_PARTY_LICENSES.md` — the license of every dependency; update it in
  the same commit that adds, removes or bundles one.

## Security invariants

Changes to `dbs/security/` must preserve these:

- **Never pickle or unpickle a model.** Estimators are refit from stored feature
  rows. Persisting a fitted estimator would put a deserialization sink in the layer
  that exists to catch intrusions.
- **Client-supplied signals may only add risk, never subtract it.** Browser
  geolocation above all: a forged "I am at the office" fix must never lower a score
  or suppress another signal. An absent signal is neutral.
- **Enforcement is server-side.** The polling endpoint is a convenience for an open
  tab; `DBSSecurityMiddleware` is the boundary.
- **A shell always beats the detector.** `manage.py dbs security unlock` must keep
  working no matter what the guard decided.
- **The panel runs no remote command.** It keeps backups in `DBS_BACKUP_DIR` and pushes
  nothing; the DBS manager pulls them. Do not bring back a console, a stored SSH credential
  or any path from a browser to a shell.
- **A flagged session changes nothing.** While a session is flagged, every unsafe method
  anywhere in the admin, and every download or export, is refused.
- **Learning never switches enforcement off.** It mutes only the anomaly model; the rules and
  both thresholds apply from the first request.
- **`X-Forwarded-For` is believed only from `DBS_TRUSTED_PROXIES`.** An address the guard
  cannot read counts as a new network, never as a trusted one.

## Upgrade path

`dbs/upgrade.py` is the executable version of the changelog. When a change requires a
developer to do something to their project — a new migration, a new or renamed setting, a
changed default, a new `INSTALLED_APPS`/`MIDDLEWARE` entry, a new dependency, a
`FORMAT_VERSION` bump — add a step to `dbs/upgrade.py` **in the same commit**, with a test.
The changelog says what changed; `manage.py dbs upgrade` checks and repairs it. A release
that needs manual steps and ships no upgrade step is incomplete.

Bump `FORMAT_VERSION` when the container layout changes; never change `MAGIC`. Old files
must stay parseable so `dbs upgrade --backups` can find and convert them, and so a mismatch
reports a version rather than "not a DBS container". Register the conversion in `CONVERTERS`
in the same commit.

The converter must never destroy its source: write a new file, validate it end to end, and
leave the original alone. Nothing in DBS deletes or overwrites a backup file — not with a
flag, not with confirmation. Abandoning unreadable backups stays behind an interactive typed
confirmation with no programmatic bypass, and the message offers installing the older
version to read them before it offers giving them up.

## Manager constraints

- `dbs.manager` is never in a host project's `INSTALLED_APPS`. The core never imports
  `dbs.manager` or `rest_framework`; a test runs a backup and checks neither was loaded.
- The embedded app never contacts the manager and stores nothing about it. Audit rows
  record the process — action, file, size, digest, outcome, timings — never who or what
  started it. Do not add a source, origin or caller field to `AuditEvent`, and do not name
  temporary files after the manager.
- Manager code is Python 3.9 syntax and Django 4.2–6.x compatible, like the rest of the
  package: no PEP 695 generics, `Self`, `StrEnum`, `datetime.UTC` or
  `CheckConstraint(condition=...)`.
- Remote commands are fixed argument lists; passphrases travel on stdin. A server's backup
  passphrase is stored once, before its first backup, and never changed: older backups would
  no longer open.
- The manager pulls; a server never pushes. It removes a server's copy only after its own
  copy is verified, keeps at most five good backups per server and plan, and never deletes
  the newest one that passed verification.
- Every service method that acts names its capability with `@requires`. The interface hides
  what a role cannot do, but the service is the boundary.
- The MCP server never accepts the account password, never returns a secret, and offers no
  tool that restores, redeploys or reverts for real, removes, deletes, pushes a `.env` or
  re-pins a host key. It pins a new server's host key only after a person confirmed it, cannot
  make a plan keep fewer backups, and cannot save a file the manager keeps encrypted.
  `tests/manager/mcp/test_tools.py` enforces the list; keep it when adding tools.
- The built interface is generated at release time and never committed.

## Install constraint

`pip install django-dbs` is the backup library alone. Code outside `dbs/security/`,
`dbs/transports/` and `dbs/manager/` must import without scikit-learn, paramiko,
djangorestframework, waitress or keyring; each extra is named in `pyproject.toml` and
`dbs/extras.py`, and a missing one is reported with the `pip install "django-dbs[EXTRA]"`
line that fixes it, never a traceback. A new dependency gets an upper bound below its next
major version.

## Test

```bash
pip install -e ".[dev]"  # every extra and the test tools
scripts/test.sh          # pytest, then pytest tests/manager --ds=tests.manager.settings
```

`DBS_TEST_DB=postgres|mysql` runs the library suite on another database and
`DBS_MANAGER_DATABASE_URL` the manager suite; `DBS_TEST_SSH_*` points the OpenSSH tests at
a server (`scripts/openssh_test_server.sh` starts one), and `DBS_STRESS_FLIPS` sets how many
bytes `scripts/stress_roundtrip.py` damages.

The session guard scores time of day, so a test that asserts a verdict tier is
time-dependent. `DBS_TEST_HOUR=3 pytest` runs the suite as though it were 03:00 UTC.
Pin the policy thresholds rather than assuming which tier a score lands in.
