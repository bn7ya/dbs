## What changes

## Why

## Stability

- [ ] Nothing a released version offers is removed, renamed or changed: the Python API,
      commands and options, settings and their defaults, `--json` keys, REST routes and fields,
      MCP tools and their inputs.
- [ ] Backups and sealed data written by 0.8.0 or later still open; migrations only add.
- [ ] `tests/test_stability.py` and `tests/manager/test_stability.py` pass, and nothing under
      `tests/stability/` was edited.

## Checks

- [ ] Tests come with the change, and `scripts/test.sh` and `ruff check .` pass.
- [ ] `CHANGELOG.md` says what changed under *Unreleased*, with a step in `dbs/upgrade.py` for
      anything a project may want to do.
