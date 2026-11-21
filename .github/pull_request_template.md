## What changes

## Why

## Stability

- [ ] Nothing a released version offers is removed, renamed or changed: the Python API,
      commands and options, settings and their defaults, `--json` keys, REST routes and fields,
      MCP tools and their inputs.
- [ ] Backups and sealed data written by 0.8.0 or later still open; migrations only add.
- [ ] `tests/test_stability.py` and `tests/manager/test_stability.py` pass, and nothing under
      `tests/stability/` was edited.

## Scope

- [ ] The change stays in the functions the request targets; nothing else was rewritten, moved,
      renamed or tidied.
- [ ] The architecture, and the backup and block code in `dbs/engine/`, `dbs/container/` and
      `dbs/crypto/`, are unchanged, or this pull request asks for that change by name and says
      why.
- [ ] Made with an AI assistant? Its plan was approved before its first edit.

## Checks

- [ ] Tests come with the change, and `scripts/test.sh` and `ruff check .` pass.
- [ ] `CHANGELOG.md` says what changed under *Unreleased*, with a step in `dbs/upgrade.py` for
      anything a project may want to do.
