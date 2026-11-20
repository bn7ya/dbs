# DBS 0.9.2 — release notes

```bash
pipx upgrade django-dbs            # on the machine the DBS manager runs on
pip install --upgrade django-dbs   # in a project
```

0.9.2 fixes the DBS manager's server move onto a server whose SSH user is not root, and its
check of an application whose folders are Docker volumes. A move of a Compose application that
keeps its data in named volumes stopped at a large image and again at the first volume, and the
moved application's check then reported folders missing that were there. Where the SSH user is
root, none of this happened.

Only the machine the manager runs on needs the new version. It has no migration to run, and a
server may stay on 0.9.x or on any 0.8 release. In a project, `python manage.py dbs upgrade`
has nothing new to do.

The full list is in the
[changelog](https://github.com/bn7ya/dbs/blob/main/CHANGELOG.md#092---2026-11-21). 0.9.2
includes everything in 0.9.0 and 0.9.1; coming from 0.8.x, read the
[0.9.0 release notes](https://github.com/bn7ya/dbs/blob/v0.9.0/RELEASE_NOTES.md) first: they
say what 0.9 brings, and the one thing that changes for a project that upgrades. Coming from
0.7.x, start with the
[0.8.0 release notes](https://github.com/bn7ya/dbs/blob/v0.8.0/RELEASE_NOTES.md).

**Nothing you use changes.** 0.9.2 adds no name and removes or changes none: your backups
restore with the same passphrase, and the Python API, commands, settings, the manager's REST
API and MCP tools work as they did in 0.9.1.
[Stability](https://github.com/bn7ya/dbs/blob/main/docs/stability.md) says what is covered.

## Fixed

- **Large images and volumes have the time they need.** On the new server, a move loads each
  image, extracts each carried folder and volume, imports each Podman volume and sets each
  carried folder's owner and mode. Those commands ran with the 20-second limit of a quick
  remote command, so `docker load` of a large image failed with `remote_command_timed_out`
  while Docker went on and loaded it. They now have as long as a backup command.
- **A volume only root can read is checked through `sudo`.** Before it fills a new volume, a
  move checks that the volume is empty. It listed the volume's folder under `/var/lib/docker`
  as the SSH user, which only root may read, and stopped with `remote_permission_denied`. It
  now asks through `sudo`, with the password typed for the move, and still never writes over
  a volume that holds something.
- **A backup folder the SSH user cannot see is left as it is.** When the application's backup
  folder sat in a Docker volume on the new server, the move took it for missing and ran
  `install -d -m 0750` over it, changing its owner and mode. It now asks through `sudo` and
  leaves a folder that is there untouched.
- **The check asks the container.** For an application in a container, the check looks for
  its file roots and backup folder on the host through the mounts. A named volume under
  `/var/lib/docker` cannot be seen there by an SSH user who is not root, so the check reported
  `root_missing` and `backup_dir_missing` and the application read *problem*. It now asks the
  container when the host path cannot be seen.

## Upgrading

On the manager's machine:

```bash
pipx upgrade django-dbs
```

and start `django_dbs run` again. From 0.9.0 the manager can also do it itself: *Update DBS* on
the **About** page, or `django_dbs update` in a terminal with the manager stopped.

A move that stopped at an image or a volume resumes where it stopped once the manager runs
0.9.2: `django_dbs server move OLD --to NEW --real --resume JOB`.
