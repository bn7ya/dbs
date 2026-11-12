# DBS 0.8.2 — release notes

```bash
pipx upgrade django-dbs            # on the machine the DBS manager runs on
pip install --upgrade django-dbs   # in a project
```

0.8.2 changes one thing: a project's `.env` no longer has to be beside `manage.py` for DBS to
find it. On 0.8.1, discovery offered a project on the server only the `.env` files in the
folder that holds `manage.py`, so a project that keeps its `.env` beside its settings, or one
folder up, was added with none. The manager took the full path of a `.env` in any folder
already, and still does; what changes is where DBS looks by itself.

Only the machine the manager runs on needs the new version. It has no migration to run, and a
server may stay on 0.8.0 or 0.8.1. In a project, `python manage.py dbs upgrade` has nothing new
to do.

The full list is in the
[changelog](https://github.com/bn7ya/dbs/blob/main/CHANGELOG.md#082---2026-11-12). 0.8.2
includes everything in 0.8.1; coming from 0.8.0, read the
[0.8.1 release notes](https://github.com/bn7ya/dbs/blob/v0.8.1/RELEASE_NOTES.md) too. Coming
from 0.7.x, read the
[0.8.0 release notes](https://github.com/bn7ya/dbs/blob/v0.8.0/RELEASE_NOTES.md) first: they
say what 0.8 brings and how to upgrade.

**Nothing you use changes.** 0.8.2 adds no name and removes or changes none: your backups
restore with the same passphrase, and the Python API, commands, settings, the manager's REST
API and MCP tools work as they did in 0.8.1.
[Stability](https://github.com/bn7ya/dbs/blob/main/docs/stability.md) says what is covered.

## Changed

- **Discovery looks in three places** for the `.env` of a project that runs on the server
  itself: beside `manage.py`, beside the settings module, and in the folder above the project.
  The project's own come first, and the first one is filled in. The other two places are
  searched only where no other account can write to the folder or its parent.
- **`manage.py dbs connection`** names the `.env` from the same three places, in the same
  order. Its `env_path` was empty unless a `.env` sat beside `manage.py`. This is what tells
  the manager about a `.env` inside a container, so it takes effect once the project itself
  runs 0.8.2.
- **The application wizard says where to enter a `.env` it did not find**: its full path, in
  the next step, under *Show more settings*. The answer to *Where do its settings come from?*
  now reads "A .env file on the server".

A `.env` in any other folder is not found by itself. Type its full path or browse to it in the
application's settings, or pass `--env-path` to `django_dbs app add` or `django_dbs app edit`.

## Upgrading

On the manager's machine:

```bash
pipx upgrade django-dbs
```

Then search the folder again from the application wizard, or with
`django_dbs app discover SERVER --folder FOLDER`. An application added on 0.8.0 or 0.8.1 keeps
the `.env` path it has; if it was added with none, enter the path in its settings.

In a project, `pip install --upgrade django-dbs` is enough.
