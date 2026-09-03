## django-dbs

This project uses django-dbs for backups.

- Setup: `dbs` in `INSTALLED_APPS` (with `django.contrib.admin` for the panel),
  `dbs.security.middleware.DBSSecurityMiddleware` in `MIDDLEWARE` for the guard, then
  `manage.py migrate`. Upgrading from 0.2.x requires that migrate.
- Commands: `python manage.py dbs backup|restore|validate|schedule|key|security|ai`.
  `manage.py django-dbs` and the older `dbs_backup`/`dbs_restore`/`dbs_validate`/
  `dbs_schedule` names also work.
- The backup passphrase is derived from `settings.SECRET_KEY`. Never hard-code one, and
  never pass one as a shell argument. Warn before any `SECRET_KEY` change: backups encrypted
  under a lost key, absent from `SECRET_KEY_FALLBACKS`, cannot be opened.
- Restores merge by default; `--flush` replaces; `--dry-run` rehearses in a rolled-back
  transaction. Suggest a dry run first.
- The admin panel is at `/admin/dbs/`, superusers only, and every request through it is
  scored by an anomaly detector that can end the session. Recover with
  `manage.py dbs security unlock USER`.
- `DBS_ADMIN_CONSOLE_SHELL = True` grants any superuser arbitrary remote command execution
  from a browser. It is off by default. Do not enable it without asking.

Full instructions: `python manage.py dbs ai` writes them into `.claude/skills/django-dbs/`.
