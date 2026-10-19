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
`dbs/connection.py`, `dbs/job_process.py`, the internals of `dbs/engine/`, `dbs/container/`
and `dbs/crypto/` (`pipeline.py`, `frames.py`, `inputs.py`, `convert.py`, `stream.py`, `rs.py`,
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
- `dbs/transports/` — the SSH/SFTP API: host-key-checked sessions, streamed remote commands
  with idle and total deadlines, interactive terminals, transfers through private partial
  files.
- `dbs/extras.py` — the one list of the packages `pip install django-dbs` brings and the
  repair line for a broken install; `tests/test_packaging.py` keeps it in step with
  `pyproject.toml`.
- `dbs/management/commands/` — the `dbs` umbrella and its `django_dbs` and `django-dbs`
  aliases (real modules), plus `dbs_backup`, `dbs_restore`, `dbs_validate`, `dbs_schedule`, `dbs_connection`,
  `dbs_health`, `dbs_audit`, `dbs_key`, `dbs_security`, `dbs_ai`, `dbs_upgrade`.
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
  backup folder, linked into place under a backup name; `--progress-seconds` lines.
- `dbs/job_process.py` — panel backups, restores and scheduled runs in a low-priority child
  process (`python -m dbs.job_process`) that reads its spec, passphrase included, from stdin,
  holds the job's leases and stops itself at `DBS_JOB_TIME_LIMIT` or `DBS_JOB_MEMORY_LIMIT`;
  the parent settles whatever a killed child left. `DBS_JOB_PROCESS = False` keeps the thread.
- `dbs/files.py` — the files a backup reads and a restore stages, checks and places, within
  the restore roots and `DBS_RESTORE_PATH_MAP`.
- `dbs/manager/` — the standalone DBS manager (`django_dbs run`): its
  own Django project (`dbs/manager/settings.py`), one app labelled `dbs_manager` with a
  subpackage per slice, the job runner and scheduler that replace Celery, and the built
  interface in `dbs/manager/static/dbs_manager/` (generated, not committed).
- `dbs/manager/servers/` and `dbs/manager/applications/` — a server is an SSH machine (address,
  pinned host key, sealed credentials, the container engines it has); an application is one
  Django project on it, run on the server itself, in a Compose service or in a container, with
  Docker or Podman. Backups, plans, `.env` versions, files and redeploys belong to an
  application. `applications/services/discovery_service.py` finds an application from a
  folder (containers by Compose labels and bind mounts, its Python, `manage.py`,
  `dbs connection --json`, `.env` candidates); `applications/paths.py` maps container paths to
  host paths through the mounts. `servers/gateways/ssh_gateway.py` runs every remote command,
  and inside a container streams files over stdin (`RECEIVE_FILE`, `READ_SMALL`) instead of
  copying them through the host.
- `dbs/manager/legacy.py` — reads a 0.7 export into the 0.8 shape (each old server becomes a
  server and an application with the old id) and keeps a copy of a SQLite database before
  the 0.8.0 migrations split it.
- `dbs/manager/permissions.py` — the one role policy: each capability names the least role
  (viewer, operator, admin, master) that may use it, and `@requires` on a service method
  enforces it for the REST views, the terminal and the MCP server alike.
- `dbs/manager/keystore.py` — the sealing key in the system keychain, or in the data folder
  where none works (`DBS_MANAGER_KEY_STORE`). `dbs/manager/staging.py` — `django_dbs import`
  built in a staging folder and swapped in, the old installation moved aside.
  `dbs/manager/recovery.py` — at start, interrupts jobs no live process runs and frees their
  locks.
- `dbs/manager/terminal/` — the manager's terminal commands (`django_dbs server|app|backup|
  plan|activity|env|files|redeploy`). Like the REST views, each verb validates with the slice's
  serializer and calls the slice's service; neither adapter holds business logic.
  `parsers.py` imports no Django, so `--help` stays instant.
- `dbs/manager/redeploy/` — moving an application onto another, deploying one in place from
  the step catalogue (`catalogue.py`, `deploy.py`), and putting either back from its safety
  backup.
- `dbs/manager/console/` — `POST /api/console/`: one terminal command line run as the
  signed-in account through the same parsers and handlers, without the verbs that read the
  manager's own disk or stdin; jobs it starts are returned, not waited for.
- `dbs/manager/shell/` — the interactive terminal on a server or inside an application's
  container: `sessions.py` holds each shell's SSH channel and output buffer in the manager
  process, `service.py` opens, polls, sweeps and closes them.
- `dbs/manager/mcp/` — `django_dbs mcp`, the MCP server Claude drives: `protocol.py` is
  JSON-RPC over stdio with no Django, `tools.py` the tools, each calling a slice's service.
- `dbs/manager/adapters/` — the glue the terminal and MCP share: references by name or id,
  serializer validation, job results, the check summary, discovery and multi-application
  takes.
- `manager-ui/` — the manager's Angular source (Angular Material, Font Awesome Free).
  `scripts/build_manager_ui.sh` builds it into the package; `manager-ui/CLAUDE.md` holds
  its rules.
- `tests/` — pytest suite (pytest-django); `tests/fake_ssh.py` is the paramiko
  stand-in used by the transport and manager tests, and `tests/test_ssh_openssh.py` runs
  against a real OpenSSH server when `DBS_TEST_SSH_*` names one. `tests/manager/` is the
  manager's suite, run as a second session with its own settings; `tests/manager/factories.py`
  makes servers and applications. `tests/isolation/` (panel jobs in real child processes,
  failing backups, several instances on one database), `tests/scaling/` (many applications on
  one manager, a file database), `tests/scale/` (a thousand tables and a large table) and
  `tests/load/` (a backup under web load; `scripts/load_backup.py` writes `load-report.md`)
  each run as their own session with their own settings. `tests/manager/live/` drives a real
  Docker or Podman Compose project (`tests/containers/project/`, built by
  `scripts/container_fixture.sh ENGINE DIR`) over OpenSSH when `DBS_TEST_CONTAINER_ENGINE`
  names an engine. `scripts/upgrade_rehearsal.py` installs 0.7.0 from PyPI, fills a project and
  a manager, upgrades both to the checkout and checks that nothing was lost.
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
  or any path from the panel to a shell.
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
- Remote commands are fixed argument lists; passphrases travel on stdin. An application's
  backup passphrase is stored once, before its first backup, and never changed: older backups
  would no longer open. Discovery runs nothing in a folder, or a project below it, that others
  can write to, and the manager reads or replaces no `.env` in such a folder.
- Adding an application and changing what it runs (`RUN_FIELDS` in
  `applications/services/application_service.py`) need the account password at any time;
  only an application exactly as a discovery in the same call found it skips it
  (`found_by_discovery`), so the REST API never does. `python_path` names a Python and
  `manage_path` a `manage.py`, never an option.
- The manager pulls; a server never pushes. It removes a server's copy only after its own
  copy is verified, keeps at most five good backups per application and plan, and never
  deletes the newest one that passed verification.
- Application ids are the ids of the 0.7 servers they came from, so the hash-chained audit
  rows keep pointing at the right thing. Never rewrite an audit row's subject or data.
- Every service method that acts names its capability with `@requires`. The interface hides
  what a role cannot do, but the service is the boundary.
- The MCP server never accepts the account password, never returns a secret, and offers no
  tool that restores, deploys, redeploys or reverts for real, changes deploy steps, pauses a
  plan, removes, deletes, pushes a `.env` or re-pins a host key, and none whose name holds
  `shell`, `terminal`, `console`, `exec` or `pty`. It pins a new server's host key only after a
  person confirmed it, cannot make a plan keep fewer backups, and cannot save a file the
  manager keeps encrypted.
  `tests/manager/mcp/test_tools.py` enforces the list; keep it when adding tools.
- A deploy runs only steps from the fixed catalogue in `dbs/manager/redeploy/catalogue.py`,
  each a fixed argument list with validated names; never accept a command line or an argument
  list from a request. A deploy backs the application up first, and its rehearsal only reads.
- The terminal opens for a signed-in admin only (`DBS_MANAGER_TERMINAL` or
  `django_dbs run --terminal` narrows it to the master or switches it off), asks the account
  password for every shell, and closes on sign-out, a password or role change, 15 minutes
  without input, a minute without a poll or two hours in all; at most four run at once, two
  per account. Its audit row records where, the size, how long, the bytes each way and why it
  closed, never what was typed or shown. The MCP server and the console never reach it.
- The built interface is generated at release time and never committed.

## Install constraint

`pip install django-dbs` installs everything DBS uses: the library, scikit-learn for the
guard, paramiko for SSH, and djangorestframework, waitress and keyring for the manager. There
are no extras (the old names `guard`, `manager`, `ssh`, `all` stay empty for 0.8 only). Code
outside `dbs/security/`, `dbs/transports/` and `dbs/manager/` still imports none of those
packages, so a project's web process stays light; a package that cannot be imported is
reported with the `pip install --force-reinstall "django-dbs"` line, never a traceback. A new
dependency gets an upper bound below its next major version.

## Test

```bash
pip install -e ".[dev]"  # everything DBS uses and the test tools
scripts/test.sh          # pytest, then tests/manager, tests/isolation, tests/scaling,
                         # tests/load and tests/scale, each with --ds=tests.<suite>.settings
```

`DBS_TEST_DB=postgres|mysql` runs the library suite on another database and
`DBS_MANAGER_DATABASE_URL` the manager suite; `DBS_TEST_SSH_*` points the OpenSSH tests at
a server (`scripts/openssh_test_server.sh` starts one), `DBS_TEST_CONTAINER_ENGINE=docker|podman`
with `DBS_TEST_CONTAINER_FOLDER` the live container tests, `DBS_TEST_FULL_DISK` a small tmpfs
for the full-disk backup, `DBS_SCALE_TABLES` and `DBS_SCALE_ROWS` the scale suite, and
`DBS_STRESS_FLIPS` how many bytes `scripts/stress_roundtrip.py` damages.

The session guard scores time of day, so a test that asserts a verdict tier is
time-dependent. `DBS_TEST_HOUR=3 pytest` runs the suite as though it were 03:00 UTC.
Pin the policy thresholds rather than assuming which tier a score lands in.
