# DBS settings reference

| Setting | Purpose |
|---|---|
| `DBS_EXCLUDE_MODELS` | `["app.Model", ...]` skipped in addition to the defaults. Prefix with `-` to re-include a default-skipped model. |
| `DBS_FILE_ROOTS` | Extra directories embedded in every backup. |
| `DBS_RESTORE_ROOTS` | Directories file restores may write into (falls back to `DBS_FILE_ROOTS`). |
| `DBS_SSH_TARGETS` | Named SFTP connection profiles defined in settings; read-only in the admin. |
| `DBS_BACKUP_DIR` | Default output directory for the scheduler. |
| `DBS_BACKUP_PREFIX` | Default backup filename prefix. |
| `DBS_SCHEDULE_INTERVAL` | Default scheduler interval (default `24h`). |
| `DBS_SCHEDULE_KEEP` | Default local retention count (default 7). |
| `DBS_SCHEDULE_PUSH_TARGET` | Default `DBS_SSH_TARGETS` entry to push to. |
| `DBS_SCHEDULE_KEEP_REMOTE` | Default retention count for pushed backups. |
| `DBS_PASSPHRASE` | Explicit passphrase, overriding the one derived from `SECRET_KEY`. |
| `DBS_MAX_UPLOAD_BYTES` | Admin restore upload cap (default 1 GiB). |
| `DBS_MAX_PAYLOAD_BYTES` | Decompressed payload cap on restore (default 4 GiB). |
| `DBS_KDF_TIME_COST` / `DBS_KDF_MEMORY_COST` / `DBS_KDF_PARALLELISM` | Argon2id cost for new backups. |
| `DBS_ADMIN_CONSOLE_SHELL` | Allow free-form SSH commands from the admin console. Default `False`. |
| `DBS_ANOMALY_ENFORCE` | Whether a blocking verdict ends sessions. Default `True`. |
| `DBS_ANOMALY_DETECTOR` | Dotted path to a replacement detector class. |
| `DBS_ANOMALY_MIN_ROWS` | Events before a per-user model is fitted (default 50). |
| `DBS_TRUSTED_NETWORKS` | CIDRs scored but never enforced against. |
| `DBS_GUARD_POLL_SECONDS` | How often the admin page re-checks authorization (default 15). |
| `DBS_GUARD_EVERYWHERE` | Extend the guard poller to the whole admin. Default `False`. |
| `DBS_GEOLOCATION` | Collect browser location as an anomaly signal. Default `False`. |
| `DBS_SECURITY_RETENTION_DAYS` | Telemetry retention for `dbs security purge` (default 90). |
| `DBS_SETUP_WIZARD` | Redirect superusers to the setup wizard until configured. Default `True`. |
| `DBS_TRUST_FORWARDED_FOR` | Read the client IP from `X-Forwarded-For`. Only enable behind a proxy that overwrites it. Default `False`. |
