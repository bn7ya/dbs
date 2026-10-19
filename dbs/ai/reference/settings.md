# DBS settings reference

Every setting is optional; DBS works with none of them set.

## What to back up

| Setting | Purpose |
|---|---|
| `DBS_EXCLUDE_MODELS` | Models skipped in addition to the defaults. A `-label` prefix re-includes a default-skipped or unmanaged model |
| `DBS_FILE_ROOTS` | Extra directories embedded in every backup |
| `DBS_RESTORE_ROOTS` | Directories a restore may write into (falls back to `DBS_FILE_ROOTS`) |
| `DBS_RESTORE_PATH_MAP` | `{"/old/root": "/new/root"}`: where a restore puts files from a server whose paths differ. Each new root must be inside a restore root |

## Where backups go

| Setting | Purpose |
|---|---|
| `DBS_BACKUP_DIR` | Where backups are kept (at most five), restored from in the panel, and checked by health |
| `DBS_SCHEDULER` | `"thread"` (default), `"command"` or `"off"`: where the panel's schedule runs |
| `DBS_BACKUP_PREFIX` | Default backup filename prefix |
| `DBS_SCHEDULE_INTERVAL` | Seeds the panel's first schedule; default for `dbs schedule` flags (default `24h`) |
| `DBS_SCHEDULE_KEEP` | Seeds the panel's first schedule; default local retention, 1 to 5 (default 5) |

## Panel jobs

Panel backups, panel restores and scheduled backups run in a child process,
`python -m dbs.job_process`, that reads its spec and passphrase from standard input.

| Setting | Purpose |
|---|---|
| `DBS_JOB_PROCESS` | `False` runs jobs in a thread of the web process, with no time or memory limit. Default `True` |
| `DBS_JOB_TIME_LIMIT` | How long a job may run before it is stopped and fails with `time_limit` (default `"6h"`) |
| `DBS_JOB_MEMORY_LIMIT` | How much memory a job may use before it fails with `memory_limit`, as `512M` or `2G`; `0` for none (default `"2G"`) |
| `DBS_JOB_NICE` | How much the child lowers its priority (default 10) |
| `DBS_JOB_PYTHON` | The interpreter that runs the child, when the project's own is not the one DBS finds, as under uWSGI or mod_wsgi |
| `DBS_JOB_BOOTSTRAP` | A dotted path to a callable that sets Django up in the child instead of `django.setup`, such as `configurations.setup` |

A child that dies fails its job as `killed` and its leases are freed. `dbs upgrade` starts
the interpreter and checks it can load the project; `dbs health` names it and the limits.

## Encryption

| Setting | Purpose |
|---|---|
| `DBS_PASSPHRASE` | Explicit passphrase, overriding the one derived from `SECRET_KEY`. Never change it once backups exist |
| `DBS_KDF_TIME_COST` / `DBS_KDF_MEMORY_COST` / `DBS_KDF_PARALLELISM` | Argon2id cost for new backups. A time cost above 10 or a memory cost above 262144 KiB makes every backup fail |

## The panel and its guard

| Setting | Purpose |
|---|---|
| `DBS_SETUP_WIZARD` | Redirect superusers to the setup wizard until configured. Default `True` |
| `DBS_ANOMALY_ENFORCE` | Whether a blocking verdict ends sessions. Default `True` |
| `DBS_TRUSTED_NETWORKS` | CIDRs scored but never enforced against |
| `DBS_ANOMALY_DETECTOR` | Dotted path to a replacement detector class |
| `DBS_ANOMALY_MIN_ROWS` | Events before a per-account model is fitted (default 50) |
| `DBS_GUARD_POLL_SECONDS` | How often an open page re-checks authorization (default 15) |
| `DBS_GUARD_EVERYWHERE` | Extend the guard poller to the whole admin. Default `False` |
| `DBS_GEOLOCATION` | Collect browser location as a signal. Default `False` |
| `DBS_SECURITY_RETENTION_DAYS` | Telemetry older than this is purged automatically, once a day (default 90) |
| `DBS_MAX_UPLOAD_BYTES` | Restore upload cap (default 1 GiB) |
| `DBS_MAX_PAYLOAD_BYTES` | Decompressed payload cap when restoring a format 1 backup (default 4 GiB) |
| `DBS_TRUST_FORWARDED_FOR` | Read the client IP from `X-Forwarded-For`. Default `False` |
| `DBS_TRUSTED_PROXIES` | The proxies' networks as CIDRs, e.g. `["10.0.0.0/24"]`. The header is read only from them |

Trusted networks and proxies no wider than /8 (v4) or /16 (v6); wider entries are refused by
the form and ignored when read, so a guarded session cannot trust the whole internet.

## Removed

`DBS_SSH_TARGETS`, `DBS_SCHEDULE_PUSH_TARGET`, `DBS_SCHEDULE_KEEP_REMOTE` and
`DBS_ADMIN_CONSOLE_SHELL` went with the panel's SFTP targets and console. `dbs upgrade`
reports them; delete them. The DBS manager pulls off-site copies.

## The DBS manager

The manager is not configured through Django settings. It reads environment variables:
`DBS_MANAGER_HOME` (the data folder), `DBS_MANAGER_DATABASE_URL` (PostgreSQL or MySQL
instead of SQLite), `DBS_MANAGER_KEY_STORE` (`keychain` or `file`, where the sealing key
lives), `DBS_MANAGER_HOST` (the name browsed to behind a proxy),
`DBS_MANAGER_TRUSTED_PROXY` (the proxy ranges `--trusted-proxy` sets) and
`DBS_MANAGER_TERMINAL` (`admins`, `master` or `off`: who may open a terminal, as
`--terminal` sets it).
