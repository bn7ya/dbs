# DBS settings reference

Every setting is optional; DBS works with none of them set.

## What to back up

| Setting | Purpose |
|---|---|
| `DBS_EXCLUDE_MODELS` | Models skipped in addition to the defaults. A `-label` prefix re-includes a default-skipped model |
| `DBS_FILE_ROOTS` | Extra directories embedded in every backup |
| `DBS_RESTORE_ROOTS` | Directories a restore may write into (falls back to `DBS_FILE_ROOTS`) |

## Where backups go

| Setting | Purpose |
|---|---|
| `DBS_BACKUP_DIR` | Default output directory for `dbs schedule` |
| `DBS_BACKUP_PREFIX` | Default backup filename prefix |
| `DBS_SCHEDULE_INTERVAL` | Default scheduler interval (default `24h`) |
| `DBS_SCHEDULE_KEEP` | Default local retention count (default 7) |
| `DBS_SSH_TARGETS` | Named SFTP profiles defined in settings; read-only in the admin |
| `DBS_SCHEDULE_PUSH_TARGET` | Default target to push to |
| `DBS_SCHEDULE_KEEP_REMOTE` | Default retention for pushed backups |

## Encryption

| Setting | Purpose |
|---|---|
| `DBS_PASSPHRASE` | Explicit passphrase, overriding the one derived from `SECRET_KEY` |
| `DBS_KDF_TIME_COST` / `DBS_KDF_MEMORY_COST` / `DBS_KDF_PARALLELISM` | Argon2id cost for new backups |

## The panel and its guard

| Setting | Purpose |
|---|---|
| `DBS_SETUP_WIZARD` | Redirect superusers to the setup wizard until configured. Default `True` |
| `DBS_ADMIN_CONSOLE_SHELL` | Allow free-form SSH commands from the console. Default `False` |
| `DBS_ANOMALY_ENFORCE` | Whether a blocking verdict ends sessions. Default `True` |
| `DBS_TRUSTED_NETWORKS` | CIDRs scored but never enforced against |
| `DBS_ANOMALY_DETECTOR` | Dotted path to a replacement detector class |
| `DBS_ANOMALY_MIN_ROWS` | Events before a per-account model is fitted (default 50) |
| `DBS_GUARD_POLL_SECONDS` | How often an open page re-checks authorization (default 15) |
| `DBS_GUARD_EVERYWHERE` | Extend the guard poller to the whole admin. Default `False` |
| `DBS_GEOLOCATION` | Collect browser location as a signal. Default `False` |
| `DBS_SECURITY_RETENTION_DAYS` | Telemetry retention for `dbs security purge` (default 90) |
| `DBS_MAX_UPLOAD_BYTES` | Restore upload cap (default 1 GiB) |
| `DBS_MAX_PAYLOAD_BYTES` | Decompressed payload cap on restore (default 4 GiB) |
| `DBS_TRUST_FORWARDED_FOR` | Read the client IP from `X-Forwarded-For`. Default `False` |
| `DBS_TRUSTED_PROXIES` | Proxies in front, counted from the right of that header (default 1) |

Trusted networks narrower than /8 (v4) or /16 (v6) only; wider entries are refused by the
form and ignored when read, so a guarded session cannot trust the whole internet.
