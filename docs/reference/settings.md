# Settings reference

Every setting is optional; DBS works with none of them set. They go in your project's Django
settings. `DBS_PASSPHRASE` is also read straight from the environment.

## Where backups go

| Setting | Default | |
|---|---|---|
| `DBS_BACKUP_DIR` | none | Where backups are kept (at most five), restored from in the panel and checked by health. The schedule, *Take a backup*, `dbs backup --stream` and health need it |
| `DBS_BACKUP_PREFIX` | `"backup"` | The file name prefix, so several projects can share a folder |
| `DBS_SCHEDULER` | `"thread"` | Where the panel's schedule runs: `"thread"` (in the web workers), `"command"` (`dbs schedule`) or `"off"` |
| `DBS_SCHEDULE_INTERVAL` | `"24h"` | Seeds the panel's first schedule, and the default interval of `dbs schedule` with plan flags |
| `DBS_SCHEDULE_KEEP` | `5` | Seeds the panel's first schedule, and how many `dbs schedule` keeps: 1 to 5 |

## What to back up

| Setting | Default | |
|---|---|---|
| `DBS_EXCLUDE_MODELS` | `[]` | Models to skip on top of the built-in exclusions. A `-app.Model` label backs up one the defaults skip, an unmanaged model included |
| `DBS_FILE_ROOTS` | `[]` | Extra folders whose files go into every backup |
| `DBS_RESTORE_ROOTS` | `DBS_FILE_ROOTS` | Folders a restore may write into |
| `DBS_RESTORE_PATH_MAP` | `{}` | `{"/old/root": "/new/root"}`: where a restore puts files from a server whose paths differ. Each new root must be inside a restore root |

## Encryption

| Setting | Default | |
|---|---|---|
| `DBS_PASSPHRASE` | derived from `SECRET_KEY` | An explicit passphrase. Never change it once backups exist |
| `DBS_KDF_TIME_COST` | `3` | Argon2id time cost for new backups; above 10 makes every backup fail |
| `DBS_KDF_MEMORY_COST` | `65536` (KiB) | Argon2id memory for new backups; above 262144 KiB makes every backup fail |
| `DBS_KDF_PARALLELISM` | `4` | Argon2id parallelism; above 16 is refused |

## Panel jobs

Panel backups, panel restores and scheduled backups run in a child process; see
[the panel guide](../panel.md#panel-jobs-run-in-a-process-of-their-own).

| Setting | Default | |
|---|---|---|
| `DBS_JOB_PROCESS` | `True` | `False` runs jobs in a thread of the web process, with no time or memory limit |
| `DBS_JOB_TIME_LIMIT` | `"6h"` | How long a job may run, as `30m`, `6h` or `1d` |
| `DBS_JOB_MEMORY_LIMIT` | `"2G"` | How much memory a job may use, as `512M` or `2G`; `0` for no limit |
| `DBS_JOB_NICE` | `10` | How much the child lowers its priority |
| `DBS_JOB_PYTHON` | the project's Python | The interpreter that runs the child, when DBS cannot find the project's own, as under uWSGI or mod_wsgi |
| `DBS_JOB_BOOTSTRAP` | `django.setup` | A dotted path to the callable that sets Django up in the child, such as `configurations.setup` |

## The panel and its guard

| Setting | Default | |
|---|---|---|
| `DBS_SETUP_WIZARD` | `True` | Sends superusers to the guard's wizard until it is configured |
| `DBS_ANOMALY_ENFORCE` | `True` | `False` never ends a session; the highest a score reaches is a flag |
| `DBS_TRUSTED_NETWORKS` | `[]` | CIDRs that are scored but never enforced against; no wider than /8 or /16 |
| `DBS_ANOMALY_DETECTOR` | the built-in one | A dotted path to a replacement detector class |
| `DBS_ANOMALY_MIN_ROWS` | `50` | Events before a per-account model is fitted |
| `DBS_GUARD_POLL_SECONDS` | `15` | How often an open page asks whether its session is still allowed |
| `DBS_GUARD_EVERYWHERE` | `False` | Extends that check to every admin page |
| `DBS_GEOLOCATION` | `False` | Adds the browser's location as a signal; it can only raise a score |
| `DBS_SECURITY_RETENTION_DAYS` | `90` | How long guard telemetry is kept |
| `DBS_TRUST_FORWARDED_FOR` | `False` | Read the client address from `X-Forwarded-For` |
| `DBS_TRUSTED_PROXIES` | `[]` | The proxies' networks, such as `["10.0.0.0/24"]`; the header is believed only from them |
| `DBS_MAX_UPLOAD_BYTES` | 1 GiB | The largest backup the panel's restore accepts as an upload |
| `DBS_MAX_PAYLOAD_BYTES` | 4 GiB | The largest decompressed payload when restoring a format 1 backup |

## Removed

`DBS_SSH_TARGETS`, `DBS_SCHEDULE_PUSH_TARGET`, `DBS_SCHEDULE_KEEP_REMOTE` and
`DBS_ADMIN_CONSOLE_SHELL` went with the panel's SFTP targets and console. `dbs upgrade` reports
them; delete them. The DBS manager pulls off-site copies.

## The DBS manager

The manager is not configured through Django settings. It reads environment variables:

| Variable | |
|---|---|
| `DBS_MANAGER_HOME` | The data folder (as `--data-dir`) |
| `DBS_MANAGER_DATABASE_URL` | `postgres://…` or `mysql://…` instead of the local SQLite file (as `--database-url`) |
| `DBS_MANAGER_KEY_STORE` | `keychain` or `file`: where the sealing key lives |
| `DBS_MANAGER_HOST` | The name you browse to, behind a proxy |
| `DBS_MANAGER_TRUSTED_PROXY` | The proxy ranges, comma-separated (as `--trusted-proxy`) |
| `DBS_MANAGER_TERMINAL` | `admins` (the default), `master` or `off`: who may open a terminal (as `--terminal`) |
