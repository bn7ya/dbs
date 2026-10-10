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
`create_backup`, `restore_backup`, `validate_backup`, `default_passphrase`.

Re-exported from `dbs/transports/__init__.py`:
`SSHTarget`, `SSHSession`, `RemoteBackup`, `RemoteResult`, `open_session`,
`push_backup`, `pull_backup`, `pull_backup_to`, `list_backups`,
`list_backup_details`, `delete_backup`, `check_connection`, `fetch_host_key`,
`HostKey`, `HostKeyError`.

Re-exported from `dbs/client/__init__.py`:
`ClientConfig`, `ServerProfile`, `load_client_config`, `resolve_client_passphrase`,
`BackupOptions`, `FetchResult`, `backup_and_fetch`.

Everything else (internal functions, classes, modules) carries no docstring and no
inline comments. That includes `dbs/naming.py`, `dbs/retention.py`,
`dbs/scheduling.py`, `dbs/io.py`, `dbs/conf.py`, `dbs/keys.py`, `dbs/models.py`,
`dbs/admin.py`, `dbs/views.py`, `dbs/forms.py`, everything under `dbs/security/`,
`dbs/client/cli.py`, `dbs/client/remote.py`, `dbs/audit.py`, `dbs/leases.py`,
`dbs/schedule_runner.py`, `dbs/health.py`, `dbs/connection.py` and everything under
`dbs/manager/`.

## Layout

- `dbs/engine/` — backup, restore, validate, payload assembly.
- `dbs/container/` — on-disk container format and blocks.
- `dbs/crypto/` — Argon2id KDF and AES-256-GCM envelope.
- `dbs/transports/` — optional SSH/SFTP transport and remote command execution.
- `dbs/client/` — the standalone `dbs-client` command (config, remote, cli).
- `dbs/management/commands/` — the `dbs` umbrella and its `django_dbs` alias, plus
  `dbs_backup`, `dbs_restore`, `dbs_validate`, `dbs_schedule`, `dbs_key`,
  `dbs_security`, `dbs_ai`.
- `dbs/contrib/` — the original standalone download/upload views, kept working.
- `dbs/models.py`, `dbs/admin.py`, `dbs/views.py`, `dbs/forms.py`,
  `dbs/templates/admin/dbs/`, `dbs/static/dbs/` — the control panel mounted at
  `/admin/dbs/`. Superusers only, enforced in `dbs/security/decorators.py` and in
  every `ModelAdmin`.
- `dbs/security/` — the session guard: feature extraction, the IsolationForest
  detector, the shipped base model, geolocation, verdicts, session termination and
  the middleware.
- `dbs/ai/` — the instructions shipped for AI coding assistants, installed by
  `manage.py dbs ai`.
- `dbs/naming.py`, `dbs/retention.py`, `dbs/scheduling.py`, `dbs/io.py`,
  `dbs/conf.py` — Django-free helpers shared by the server and the client.
- `dbs/audit.py`, `dbs/leases.py`, `dbs/schedule_runner.py`, `dbs/health.py`,
  `dbs/connection.py` — the sourceless audit trail, database leases, the panel's
  schedule and its in-process runner, the health report, and the connection details the
  manager reads.
- `dbs/manager/` — the standalone DBS manager (`django_dbs run`): its own Django project
  (`dbs/manager/settings.py`), one app labelled `dbs_manager` with a subpackage per slice,
  the job runner and scheduler that replace Celery, and the built interface in
  `dbs/manager/static/dbs_manager/` (generated, not committed).
- `dbs/manager/terminal/` — the manager's terminal commands (`django_dbs server|backup|plan|
  activity|env|files|redeploy`). Like the REST views, each verb validates with the slice's
  serializer and calls the slice's service; neither adapter holds business logic.
  `parsers.py` imports no Django, so `--help` stays instant.
- `manager-ui/` — the manager's Angular source (Angular Material, Font Awesome Free).
  `scripts/build_manager_ui.sh` builds it into the package; `manager-ui/CLAUDE.md` holds
  its rules.
- `tests/` — pytest suite (pytest-django); `tests/fake_ssh.py` is the paramiko
  stand-in used by the transport and client tests. `tests/manager/` is the manager's
  suite, run as a second session with its own settings.

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
- **The console's named actions take no user-supplied command string.** Free-form
  commands stay behind `DBS_ADMIN_CONSOLE_SHELL`, default off.

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
- Remote commands are fixed argument lists; passphrases travel on stdin.
- The built interface is generated at release time and never committed.

## Client constraint

`dbs/client/` must import and run with **no Django settings configured**. Never
import `dbs.engine` at client module import time, and read settings through
`dbs.conf.setting` — plain `getattr(settings, ...)` raises `ImproperlyConfigured`
when Django is unconfigured.

## Test

```bash
pip install -e ".[dev]"
scripts/test.sh          # pytest, then pytest tests/manager --ds=tests.manager.settings
```

The session guard scores time of day, so a test that asserts a verdict tier is
time-dependent. `DBS_TEST_HOUR=3 pytest` runs the suite as though it were 03:00 UTC.
Pin the policy thresholds rather than assuming which tier a score lands in.
