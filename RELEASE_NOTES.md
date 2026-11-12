# DBS 0.8.1 — release notes

```bash
pipx upgrade django-dbs            # on the machine the DBS manager runs on
pip install --upgrade django-dbs   # in a project
```

0.8.1 fixes one fault and what followed from it. On 0.8.0 the DBS manager kept only the first
64 KiB of what a command printed on a server. Asking Docker or Podman about more than a handful
of containers prints more than that, so the answer was cut, could not be read, and the manager
found no application on the server. It now reads everything a command prints.

Only the machine the manager runs on needs the new version. It has no migration to run, and a
server may stay on 0.8.0. In a project, `python manage.py dbs upgrade` has nothing new to do.

The full list is in the
[changelog](https://github.com/bn7ya/dbs/blob/main/CHANGELOG.md#081---2026-11-12). Coming from
0.7.x, read the
[0.8.0 release notes](https://github.com/bn7ya/dbs/blob/v0.8.0/RELEASE_NOTES.md) first: they
say what 0.8 brings and how to upgrade.

**Nothing you use changes.** 0.8.1 adds three names and removes or changes none: your backups
restore with the same passphrase, and the Python API, commands, settings, the manager's REST
API and MCP tools work as they did in 0.8.0.
[Stability](https://github.com/bn7ya/dbs/blob/main/docs/stability.md) says what is covered.

## Fixed

- **Applications on a server with many containers are found.** Discovery reported a folder as
  holding no Django project when the server's containers, inspected together, came to more
  than 64 KiB, which a handful of containers do.
- **Every container is looked at.** Discovery inspected the 30 newest containers and no
  others, so an application with older containers was not found. It now inspects every
  container, 30 at a time and up to 1,000.
- **A container removed while discovery runs** hid every other container. The ones the engine
  still describes are kept.
- **A server move** planned from such a server read none of its containers: a Compose
  application's plan carried no images or volumes, and a container application was said to be
  missing. The move reads every container, up to 1,000 where it stopped at 60.
- **A long `.env` inside a container** was kept as its first 48 KiB, with no error, in the
  versions the manager stores, the copy it takes before replacing the file among them. It is
  read whole. A `.env` on the server itself was never affected.
- **A command that prints a lot**, such as a long build in a deploy step, stood still until
  its time limit once it had printed about 2 MiB, because nothing read what it printed. Its
  output is read as it arrives.
- **`SSHSession.run()`** in your own code returns the whole output too: up to 16 MiB of
  standard output and of standard error, where it returned the first 64 KiB of each.

## Added

- `RemoteResult.stdout_truncated` is true when a command printed more standard output than
  `SSHSession.run()` (16 MiB) or `feed()` (64 KiB) keeps.
- A discovery report's `unread_containers` names each container that describes itself in more
  than 16 MiB on its own. Discovery leaves it out, and `django_dbs app discover` says so.
- A server move is blocked with `container_unread` for each container on the old server that
  describes itself in more than 16 MiB on its own, since the move cannot read what it carries.

## Upgrading

On the manager's machine:

```bash
pipx upgrade django-dbs
```

Then search the folder again from the application wizard, or with
`django_dbs app discover SERVER --folder FOLDER`. An application added on 0.8.0 keeps working
as it was; if a `.env` longer than 48 KiB lives inside its container, pull it again
(`django_dbs env pull APP`) so the manager keeps the whole file.

In a project, `pip install --upgrade django-dbs` is enough.
