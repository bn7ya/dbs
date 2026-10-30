# DBS documentation

Start at the top and stop when you have what you need. The guides go from the first steps to
the details; the reference is for looking things up.

## Guides

| Guide | Read it to… |
|---|---|
| [Getting started](getting-started.md) | Back up a project, use the panel, and run the DBS manager for the first time |
| [DBS in a Django project](project.md) | Set a project up, use the backup commands, and choose what goes into a backup |
| [The panel](panel.md) | Schedule backups, restore them and watch their health from `/admin/dbs/` |
| [The DBS manager](manager.md) | Look after the projects on your servers: servers, applications, plans, Docker and Podman, `.env` versions, the console and terminal, accounts and roles |
| [Deploying and moving](deploy-and-move.md) | Deploy in place, move to another application, or move a whole server |
| [Restoring and passphrases](restoring.md) | Know exactly what a restore does, and keep backups opening |
| [The session guard](session-guard.md) | Understand and tune the protection around the panel |
| [AI assistants](ai-assistants.md) | Give a coding assistant DBS instructions, and let Claude operate the manager |
| [How it works](how-it-works.md) | The backup format, how it heals, and the security model |

## Reference

| Reference | |
|---|---|
| [Commands](reference/commands.md) | Every `manage.py dbs` and `django_dbs` command and option |
| [Settings](reference/settings.md) | Every `DBS_*` setting and the manager's environment variables |
| [Python API](reference/python-api.md) | `dbs` and `dbs.transports` |
| [Troubleshooting](troubleshooting.md) | A symptom, and what to do about it |
| [Upgrading](upgrading.md) | What changes between releases, and what `dbs upgrade` checks |
| [Development](development.md) | Tests, the interface, the journeys, and releasing |

Security reports: [SECURITY.md](../SECURITY.md). Every change: [CHANGELOG.md](../CHANGELOG.md).
