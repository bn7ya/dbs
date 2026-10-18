## django-dbs

This project uses django-dbs for backups.

- Install: `pip install django-dbs` installs everything: the library, the session guard's
  detector, the `dbs.transports` API and the manager (`django-dbs`, `django_dbs` or `dbs`).
- Setup: `dbs` in `INSTALLED_APPS` (with `django.contrib.admin` for the panel),
  `dbs.security.middleware.DBSSecurityMiddleware` in `MIDDLEWARE` below
  `AuthenticationMiddleware` for the guard, `DBS_BACKUP_DIR`, then `manage.py migrate`.
  Upgrading from 0.2.x requires that migrate.
- Commands: `python manage.py dbs backup|restore|validate|schedule|connection|health|audit|key|security|ai|upgrade`.
  `manage.py django_dbs`, `manage.py django-dbs` and the older `dbs_backup`/`dbs_restore`/
  `dbs_validate`/`dbs_schedule` names also work. `dbs backup PATH` refuses a path that exists.
- The backup passphrase is derived from `settings.SECRET_KEY` and **must never change**:
  older backups would no longer open. Never hard-code one, and never pass one as a shell
  argument. Warn before any `SECRET_KEY` or `DBS_PASSPHRASE` change: backups encrypted under
  a lost key, absent from `SECRET_KEY_FALLBACKS`, cannot be opened.
- Restores merge by default; `--flush` replaces the rows the backup covers; `--dry-run`
  rehearses in a rolled-back transaction and names any file it would refuse. Suggest a dry
  run first.
- The admin panel is at `/admin/dbs/`, superusers only, and every request through it is
  scored by an anomaly detector that can end the session. Recover with
  `manage.py dbs security unlock USER`.
- Panel backups, restores and scheduled runs run in a child process
  (`python -m dbs.job_process`) stopped at `DBS_JOB_TIME_LIMIT` (6h) or
  `DBS_JOB_MEMORY_LIMIT` (2G); `DBS_JOB_PYTHON` names its interpreter when the web server
  embeds Python. `dbs.contrib` was removed in 0.8.0.
- The server keeps at most five backups and pushes nothing; the DBS manager pulls them over
  SSH. The panel has no SFTP targets and no console, and there is no `dbs-client`.
- The manager (`django_dbs run`) keeps servers (SSH machines) apart from applications (one
  Django project each, on the server, in a Compose service or a container, Docker or
  Podman), added from a folder with `django_dbs app add NAME --server S --folder F`. An
  application's backup passphrase is stored once and never changed. Deploy steps come only
  from its fixed catalogue; its terminal is admin only, and Claude's MCP tools never reach it
  or deploy for real.

- Run `python manage.py dbs upgrade --check` before other work, and `dbs upgrade` after
  upgrading the package. It applies pending migrations and reports anything else needed.
- **Never confirm the abandonment of backups.** If `dbs upgrade --backups` reports files it
  cannot convert, stop and tell the developer; do not type the confirmation phrase, bypass
  the prompt, or delete any `.dbs` file.

Full instructions: `python manage.py dbs ai` writes them into `.claude/skills/django-dbs/`.
