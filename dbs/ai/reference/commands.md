# DBS command reference

## `dbs backup OUTPUT`
`--passphrase`, `--passphrase-stdin`, `--database`, `--no-compress`, `--no-verify`,
`--block-size`, `--kdf-time`, `--kdf-memory`.

## `dbs restore INPUT`
`--passphrase`, `--passphrase-stdin`, `--database`, `--no-data`, `--no-files`,
`--dry-run`, `--flush`.

Merging is the default. `--flush` replaces. `--dry-run` rehearses in a rolled-back
transaction and writes no files.

## `dbs validate INPUT`
`--passphrase` (optional value; given without one it uses the derived passphrase).
Checks structure and block integrity; with a passphrase it also decrypts end to end.

## `dbs schedule`
`--interval`, `--output-dir`, `--prefix`, `--keep`, `--push`, `--keep-remote`,
`--database`, `--once`. `SIGTERM` stops the loop immediately. Run one scheduler per
output directory.

## `dbs key [--show]`
Reports where the passphrase comes from; `--show` prints it.

## `dbs security [action] [username]`
`status`, `unlock USER`, `policy`, `retrain`, `reset-baseline USER`, `events`, `purge`.

## `dbs ai [--agents] [--check] [--print]`
Installs the DBS instructions for AI assistants into the project.
