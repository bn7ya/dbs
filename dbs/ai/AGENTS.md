## django-dbs

This project uses django-dbs for backups.

- Install: `pip install django-dbs` is the backup library alone; `django-dbs[guard]` adds
  the session guard's detector, `django-dbs[manager]` the `django_dbs` manager,
  `django-dbs[ssh]` the `dbs.transports` API, `django-dbs[all]` all three.
- Setup: `dbs` in `INSTALLED_APPS` (with `django.contrib.admin` for the panel),
  `dbs.security.middleware.DBSSecurityMiddleware` in `MIDDLEWARE` below
  `AuthenticationMiddleware` for the guard, `DBS_BACKUP_DIR`, then `manage.py migrate`.
  Upgrading from 0.2.x requires that migrate.
- Commands: `python manage.py dbs backup|restore|validate|schedule|health|audit|key|security|ai|upgrade`.
  `manage.py django-dbs` and the older `dbs_backup`/`dbs_restore`/`dbs_validate`/
  `dbs_schedule` names also work. `dbs backup PATH` refuses a path that exists.
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
- The server keeps at most five backups and pushes nothing; the DBS manager pulls them over
  SSH. There are no SFTP targets, no console and no `dbs-client`.

- Run `python manage.py dbs upgrade --check` before other work, and `dbs upgrade` after
  upgrading the package. It applies pending migrations and reports anything else needed.
- **Never confirm the abandonment of backups.** If `dbs upgrade --backups` reports files it
  cannot convert, stop and tell the developer; do not type the confirmation phrase, bypass
  the prompt, or delete any `.dbs` file.

Full instructions: `python manage.py dbs ai` writes them into `.claude/skills/django-dbs/`.
