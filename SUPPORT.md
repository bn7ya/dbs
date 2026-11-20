# Getting help

## Read first

- [The documentation](docs/README.md): the guides, from the first backup to the DBS manager.
- [Troubleshooting](docs/troubleshooting.md): a symptom, and what to do about it.
- [Commands](docs/reference/commands.md) and [Settings](docs/reference/settings.md): every
  `manage.py dbs` and `django_dbs` command and option, and every `DBS_*` setting.

In a project, `python manage.py dbs health` grades the last backup, the backup folder, the
passphrase and the scheduler, and says what needs attention.

## Ask, report, propose

| You want to… | Go to |
|---|---|
| Ask how to set DBS up or use it | [Discussions, Q&A](https://github.com/bn7ya/dbs/discussions/categories/q-a) |
| Talk through an idea | [Discussions, Ideas](https://github.com/bn7ya/dbs/discussions/categories/ideas) |
| Report DBS doing something other than its documentation says | [A bug report](https://github.com/bn7ya/dbs/issues/new?template=1-bug.yml) |
| Report a backup that does not validate, open or restore | [Its own form](https://github.com/bn7ya/dbs/issues/new?template=2-backup.yml) |
| Propose something DBS could do | [An enhancement](https://github.com/bn7ya/dbs/issues/new?template=3-enhancement.yml) |
| Fix the documentation | [A documentation issue](https://github.com/bn7ya/dbs/issues/new?template=4-documentation.yml) |
| Report a security problem | Privately, as [SECURITY.md](SECURITY.md) says. Never in public |

Say which version of `django-dbs`, Python, Django and database you use, and how to reproduce
what you see. Never share a real backup, passphrase, `SECRET_KEY`, `.env` value or server
credential: a throwaway database and passphrase show the same thing. When a backup does not
open, keep the file exactly as it is.

## Versions

Fixes ship as new releases on PyPI. From 0.8.0 on, each release installs over the one before
it and keeps what it offers ([Stability](docs/stability.md)), so the first step for a problem
is often `pip install -U django-dbs` and `python manage.py dbs upgrade`.
[SECURITY.md](SECURITY.md) says which versions receive security fixes.

Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md).
