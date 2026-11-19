# DBS 0.9.1 — release notes

```bash
pipx upgrade django-dbs            # on the machine the DBS manager runs on
pip install --upgrade django-dbs   # in a project
```

0.9.1 fixes one thing, in the DBS manager: on Django 4.2 or 5.0, a write to the manager's own
SQLite database could be dropped, without an error, while another write was in progress. A
manager installed on Python 3.9 runs Django 4.2, the newest Django that Python has, so that is
where it matters. On Django 5.1 or later the manager already behaved as it does now.

Only the machine the manager runs on needs the new version. It has no migration to run, and a
server may stay on 0.9.0 or on any 0.8 release. In a project, `python manage.py dbs upgrade`
has nothing new to do.

The full list is in the
[changelog](https://github.com/bn7ya/dbs/blob/main/CHANGELOG.md#091---2026-11-19). 0.9.1
includes everything in 0.9.0; coming from 0.8.x, read the
[0.9.0 release notes](https://github.com/bn7ya/dbs/blob/v0.9.0/RELEASE_NOTES.md) first: they
say what 0.9 brings, and the one thing that changes for a project that upgrades. Coming from
0.7.x, start with the
[0.8.0 release notes](https://github.com/bn7ya/dbs/blob/v0.8.0/RELEASE_NOTES.md).

**Nothing you use changes.** 0.9.1 adds no name and removes or changes none: your backups
restore with the same passphrase, and the Python API, commands, settings, the manager's REST
API and MCP tools work as they did in 0.9.0.
[Stability](https://github.com/bn7ya/dbs/blob/main/docs/stability.md) says what is covered.

## Fixed

- **A write to the manager's database waits its turn on every Django.** The manager keeps its
  backup and server-move locks, its sign-in limits, its download tickets and the host keys
  waiting to be confirmed in a cache table of its own database. On Django 4.2 and 5.0 its
  SQLite transactions began without the write lock, and a write to that table reads before it
  writes, so one made while another connection was writing failed at once and was dropped
  without an error. A scheduled backup could be recorded as failed because another seemed to
  be running, a ticket or a host key waiting to be confirmed could be lost, a sign-in limit
  could miss a count, and `/api/health/` could answer 503 for a moment after a start.

  The manager now takes the write lock as a write begins on every Django it supports, as it
  already did from Django 5.1, so such a write waits for the other to finish, up to the
  30-second busy timeout. Where the manager's database is PostgreSQL or MySQL
  (`DBS_MANAGER_DATABASE_URL`), nothing was wrong and nothing changes.

## Upgrading

On the manager's machine:

```bash
pipx upgrade django-dbs
```

and start `django_dbs run` again. From 0.9.0 the manager can also do it itself: *Update DBS* on
the **About** page, or `django_dbs update` in a terminal with the manager stopped.

In a project, `pip install --upgrade django-dbs` is enough.
