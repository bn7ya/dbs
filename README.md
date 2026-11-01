<p align="center">
  <img src="https://raw.githubusercontent.com/bn7ya/dbs/main/docs/assets/dbs-logo.svg" alt="DBS" width="220">
</p>

<h1 align="center">DBS — Django Backup Solution</h1>

<p align="center">
  Encrypted, self-healing backups for Django projects, and a manager that looks after them on
  every server.
</p>

<p align="center">
  <a href="https://pypi.org/project/django-dbs/"><img src="https://img.shields.io/pypi/v/django-dbs" alt="PyPI version"></a>
  <a href="https://pypi.org/project/django-dbs/"><img src="https://img.shields.io/pypi/pyversions/django-dbs" alt="Python versions"></a>
  <a href="https://github.com/bn7ya/dbs/actions/workflows/ci.yml"><img src="https://github.com/bn7ya/dbs/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/bn7ya/dbs/blob/main/LICENSE"><img src="https://img.shields.io/pypi/l/django-dbs" alt="License"></a>
  <a href="#status"><img src="https://img.shields.io/badge/status-active%20development%2C%20stable%20since%200.8.0-0058a4" alt="Status: active development, stable since 0.8.0"></a>
</p>

<p align="center">
  <strong>0.8.0 is out:</strong>
  <a href="#whats-new-in-080">what's new</a> ·
  <a href="https://github.com/bn7ya/dbs/blob/v0.8.0/RELEASE_NOTES.md">release notes</a> ·
  <a href="https://github.com/bn7ya/dbs/blob/main/docs/upgrading.md">upgrading</a>
</p>

---

## What DBS does

- **One file per backup.** A backup holds your project's rows, the relations between them and
  its uploaded files, encrypted.
- **It repairs itself.** Every backup stores two copies of your data plus Reed-Solomon parity,
  so damage to the file is found and repaired when you restore, instead of quietly breaking
  the data you rely on.
- **A panel in your admin.** `/admin/dbs/` schedules backups, restores them, reports their
  health and keeps a tamper-evident audit trail, behind a session guard.
- **A manager for your servers.** `django_dbs run` starts a local application that finds the
  Django projects on your servers (on the server itself, in Compose or in a container, under
  Docker or Podman), pulls their backups to your machine, and restores, deploys or moves them.
- **Claude at the controls, safely.** Through MCP, Claude can add servers, take and verify
  backups and rehearse restores, without ever seeing a secret or changing anything for real.

## Quick start

You need Python 3.9 or later and Django 4.2 to 6.x.

**1. Back up a project.**

```bash
pip install django-dbs
```

```python
# settings.py
INSTALLED_APPS = [..., "dbs"]                  # beside django.contrib.admin
MIDDLEWARE = [..., "dbs.security.middleware.DBSSecurityMiddleware"]  # below AuthenticationMiddleware
DBS_BACKUP_DIR = "/var/backups/myproject"
```

```bash
python manage.py migrate
python manage.py dbs upgrade                            # checks the setup, says what is missing
python manage.py dbs backup backup.dbs                  # an encrypted backup
python manage.py dbs validate backup.dbs --passphrase   # check it
python manage.py dbs restore backup.dbs --dry-run       # rehearse a restore
python manage.py dbs key --show                         # keep this somewhere safe
```

The passphrase is derived from your `SECRET_KEY`, so keep `SECRET_KEY` stable.

**2. Open the panel** at `/admin/dbs/` as a superuser, and turn on **Schedule**.

**3. Look after your servers** from your own machine:

```bash
pipx install django-dbs
django_dbs run
```

Create the master account on the page that opens, add a server, then add an application by
answering *How it runs* and choosing its folder. The manager finds the project, checks it and
takes a first backup.

**4. Optionally, let Claude help:** `claude mcp add dbs -- django_dbs mcp`.

The [getting started guide](https://github.com/bn7ya/dbs/blob/main/docs/getting-started.md)
walks through each step.

## What's new in 0.8.0

- **Servers and applications.** A server is an SSH machine, and each Django project on it is an
  application, found from its folder: on the server itself, in Compose or in a container, under
  Docker or Podman.
- **How it runs.** The application wizard asks how the project is deployed, compares your
  answers with what it finds, and gives the next step for anything missing.
- **Move a whole server**, even onto one with nothing installed. The manager installs what is
  missing with `sudo`, carries the code, images, volumes and `.env`, and restores the data from
  a fresh backup. The old server keeps running untouched.
- **Deploy in place** from a fixed catalogue of steps, after a safety backup. Plans get a first
  run, a time zone and a pause, and the manager has a console and a terminal in the browser.
- **Lighter on your site.** Panel backups and restores run in a process of their own, large
  tables are read in pages, and a broken transfer resumes where it stopped.
- **One install, stable from here.** `pip install django-dbs` brings everything, and the manager
  answers to `django-dbs`, `django_dbs` and `dbs`. What 0.8.0 offers stays in every later
  release; see [Stability](https://github.com/bn7ya/dbs/blob/main/docs/stability.md).

**Upgrading from 0.7.x:**

```bash
pip install --upgrade django-dbs
python manage.py dbs upgrade
```

On the manager's machine, `pipx upgrade django-dbs`; it migrates itself the next time any
`django_dbs` command runs. The
[release notes](https://github.com/bn7ya/dbs/blob/v0.8.0/RELEASE_NOTES.md) and the
[changelog](https://github.com/bn7ya/dbs/blob/main/CHANGELOG.md) have every detail.

## How it works, in brief

- **Encryption:** Argon2id turns the passphrase into a key, and AES-256-GCM encrypts the data.
  A wrong passphrase never yields data.
- **Redundancy:** every block is stored twice, 64 blocks apart, with Reed-Solomon parity and a
  keyed tag, so a backup survives a burst of damage and scattered damage in both copies.
- **Verification:** every new backup is read back and checked before it counts.
- **Pulling, never pushing:** servers keep at most five backups each. The manager pulls them
  over SSH, verifies them and keeps at most five per application; a server never contacts it.

More in [How it works](https://github.com/bn7ya/dbs/blob/main/docs/how-it-works.md).

## Documentation

| | |
|---|---|
| [Getting started](https://github.com/bn7ya/dbs/blob/main/docs/getting-started.md) | From nothing to backups that are taken, checked and kept elsewhere |
| [DBS in a Django project](https://github.com/bn7ya/dbs/blob/main/docs/project.md) | Settings, the backup commands, large tables, and what goes into a backup |
| [The panel](https://github.com/bn7ya/dbs/blob/main/docs/panel.md) | Scheduling, restoring, health and the audit trail at `/admin/dbs/` |
| [The DBS manager](https://github.com/bn7ya/dbs/blob/main/docs/manager.md) | Servers, applications, plans, Docker and Podman, `.env` versions, console, terminal, roles |
| [Deploying and moving](https://github.com/bn7ya/dbs/blob/main/docs/deploy-and-move.md) | Deploy in place, move to another application, move a whole server |
| [Restoring and passphrases](https://github.com/bn7ya/dbs/blob/main/docs/restoring.md) | What a restore does, and keeping backups opening |
| [The session guard](https://github.com/bn7ya/dbs/blob/main/docs/session-guard.md) | The protection around the panel |
| [AI assistants](https://github.com/bn7ya/dbs/blob/main/docs/ai-assistants.md) | Instructions for coding assistants, and Claude through MCP |
| [How it works](https://github.com/bn7ya/dbs/blob/main/docs/how-it-works.md) | The format, how it heals, the security model |
| [Reference](https://github.com/bn7ya/dbs/tree/main/docs/reference) | [Commands](https://github.com/bn7ya/dbs/blob/main/docs/reference/commands.md), [settings](https://github.com/bn7ya/dbs/blob/main/docs/reference/settings.md), [Python API](https://github.com/bn7ya/dbs/blob/main/docs/reference/python-api.md) |
| [Troubleshooting](https://github.com/bn7ya/dbs/blob/main/docs/troubleshooting.md) · [Upgrading](https://github.com/bn7ya/dbs/blob/main/docs/upgrading.md) · [Stability](https://github.com/bn7ya/dbs/blob/main/docs/stability.md) · [Development](https://github.com/bn7ya/dbs/blob/main/docs/development.md) | When something does not work, between releases, what never changes, and working on DBS itself |

## What you need

- Python 3.9 or later, and Django 4.2 to 6.x.
- `pip install django-dbs` brings everything DBS uses: the backup library, scikit-learn for the
  session guard, paramiko for SSH, and djangorestframework, waitress and keyring for the
  manager. A project's web process imports only what it uses.
- The manager needs nothing else on its machine: no Node, no Docker, no Redis and no database
  server.

## Status

0.8.0 is the current release. DBS is in active development, and stable from 0.8.0: new releases
add, and nothing you use breaks.

- **Your backups keep opening.** Every backup written by 0.8.0 or later restores, with the same
  passphrase, in every later release. Nothing in DBS deletes or overwrites a backup.
- **Your project keeps working.** The Python API, commands and options, settings and their
  defaults, the manager's REST API and MCP tools stay as they are; the test suite checks every
  change against each recorded release.
- **Upgrades are checked for you.** `python manage.py dbs upgrade` checks a project after each
  upgrade, and the [changelog](https://github.com/bn7ya/dbs/blob/main/CHANGELOG.md) lists every
  change.

The full promise is in [Stability](https://github.com/bn7ya/dbs/blob/main/docs/stability.md).
To contribute, see [CONTRIBUTING.md](https://github.com/bn7ya/dbs/blob/main/CONTRIBUTING.md).

Security issues: see [SECURITY.md](https://github.com/bn7ya/dbs/blob/main/SECURITY.md).

## License and credits

MIT. The manager's interface bundles Font Awesome Free (icons under CC BY 4.0, fonts under the
SIL OFL 1.1), the Tajawal typeface (SIL OFL 1.1), qrcode-generator (MIT) and xterm.js (MIT).
[THIRD_PARTY_LICENSES.md](https://github.com/bn7ya/dbs/blob/main/THIRD_PARTY_LICENSES.md)
lists the license of every dependency.

Created by **Sudum Technology — Research and Development sector**. Our very tiny contribution
to this world.
