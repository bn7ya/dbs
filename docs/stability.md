# Stability

From 0.8.0 on, DBS keeps what it offers. Every later release installs over the one before it:
your backups keep opening, your project keeps working, and your scripts keep running. New
releases add; they do not remove, rename or change what you already use.

## What stays

**Your backups.** Every backup written by DBS 0.8.0 or later validates and restores, with the
same passphrase, in every later release. A new backup format comes with a reader for the old
one and `dbs upgrade --backups` to convert, which writes a new file beside the original.
Nothing in DBS deletes or overwrites a backup. The passphrase DBS derives from `SECRET_KEY`
stays the same, so keeping `SECRET_KEY` keeps every backup opening.

**The Python API.** Everything exported by `dbs` and `dbs.transports` (see the
[Python API reference](reference/python-api.md)), the results they return and the exceptions
in `dbs.exceptions` keep their names, parameters, defaults and fields. A new parameter is
keyword-only and defaults to what happened before.

**Commands.** Every `manage.py dbs` command and its `dbs_*`, `django_dbs` and `django-dbs`
names, and every `django_dbs` command of the manager, keep their options, arguments, exit
codes and `--json` keys. A new option or argument is optional.

**Settings.** Every setting and environment variable in the
[settings reference](reference/settings.md) keeps its name, meaning and default. A new setting
defaults to what DBS did before it existed. `pip install "django-dbs[guard]"`, `[manager]`,
`[ssh]` and `[all]` keep installing, though plain `django-dbs` already brings everything.

**Your data.** DBS's migrations only add tables and columns; they never drop, rename or retype
one. The audit trail is never rewritten, and a trail recorded by 0.8.0 still verifies.

**The DBS manager.** Its data folder, sealing key, stored credentials and the backups it keeps
open in every later release. Its REST API under `/api/` keeps every route, method, request
field and response key, and its MCP tools keep their names and inputs. A newer manager keeps
backing up servers that run django-dbs 0.8.0.

## What may change

- **Additions.** New commands, options, settings, functions, fields, routes and tools.
- **Bug fixes**, which make DBS do what this documentation says.
- **Security fixes**, which may refuse something that was unsafe. They never delete data, and
  the changelog names them under *Security*.
- **Supported versions.** A Python or Django version is dropped only after its own end of
  life, in a minor release. Its requirements stop pip from installing that release where it
  cannot run, so your environment keeps the last one that does.
- **Wording.** Help text, messages and the interface's look. Scripts should read `--json`
  output and exit codes, not the text meant for people.

## How it is kept

Each release is recorded in the repository under `tests/stability/`: its Python API, commands,
the manager's terminal, REST routes and MCP tools, settings, migrations and `--json` keys,
plus a golden backup and sealed values it wrote. The test suite compares every later change
with every recorded release and fails on anything removed or changed, and it restores the
golden backup, also after damaging it. A recorded release is never rewritten.

After each upgrade, `python manage.py dbs upgrade` checks your project and says if there is
anything to do; see [Upgrading](upgrading.md).
