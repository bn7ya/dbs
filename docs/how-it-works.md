# How it works

## In short

A DBS backup is **one file** that holds a project's rows, the relations between them and its
uploaded files. The file is:

- **encrypted** with AES-256-GCM, under a key derived from a passphrase with Argon2id;
- **redundant:** every block is stored twice, the second copy 64 blocks after the first;
- **self-healing:** every block carries Reed-Solomon parity, so damage is corrected while the
  file is read, even when both copies are hit;
- **verified when written:** a new backup is read back and checked end to end, both copies
  included, before the command reports success.

The passphrase is derived from the project's `SECRET_KEY`, so there is nothing to invent and
nothing to forget, as long as `SECRET_KEY` never changes (see
[Passphrases](restoring.md#passphrases)).

On a server, backups wait in `DBS_BACKUP_DIR`, at most five. The [DBS manager](manager.md)
connects over SSH, pulls them to its own machine, verifies them and keeps at most five per
application and plan. The server never pushes anything and never contacts the manager.

## A backup, step by step

1. Rows are read in pages keyed on the primary key, from one database snapshot, and files in
   chunks (see [Large tables](project.md#large-tables-and-large-values)).
2. The payload is compressed in 1 MiB segments.
3. Each segment is encrypted, given parity and a keyed tag, and written twice.
4. The finished file is read back and verified, then moved into place under its name.

Reading, compressing, encrypting and writing run in separate threads behind bounded queues, so
memory stays flat however large the project is. A restore reads the file the same way.

## How it heals

On write, the payload is compressed in 1 MiB segments and encrypted in chunks with
AES-256-GCM, one chunk per block. Each chunk is authenticated together with the file's header,
under a nonce that carries its position, so a block moved, swapped, dropped or taken from
another backup fails authentication. Each block gets Reed-Solomon parity and a keyed BLAKE2b
tag, and is stored **twice**: the second copy is written 64 blocks after the first, so a burst
of damage up to about 4 MiB never reaches both copies of a block. The header, which carries the
layout, the Argon2id parameters, the salt and the wrapped data key, is written at the start and
the end with a checksum, and two checksummed trailers carry the block count and a digest over
every block tag. No plain hash of your data is stored.

On read, each block is taken from whichever copy verifies, and sparse bit flips are corrected
in place even when both copies are hit. A block that neither copy yields on its own is rebuilt
from both, one 255-byte codeword at a time: each codeword comes from whichever copy decodes,
and where the two copies disagree, those bytes are treated as erasures, of which Reed-Solomon
corrects twice as many. Only a header copy that verifies is used, so damage to one never hides
a backup, and a file cut short still yields its block count from the blocks themselves.

**Recoverable:**

- whole-block loss in one copy;
- sparse byte errors in both copies, up to the parity budget (about 8 bytes per codeword by
  default);
- damage to both copies of the same block, as long as each codeword survives in one copy or
  the copies differ in at most 16 of its bytes;
- damage to one copy of the header or the trailer.

**Not recoverable:** a codeword destroyed beyond that in both copies. DBS then refuses to
restore and names the failed blocks.

When DBS heals a file, it logs a `WARNING` on the `dbs` logger, and a restore reports
`healed`.

## Format versions

This is container format 2. Backups written in format 1 by earlier releases still validate and
restore, read whole within `DBS_MAX_PAYLOAD_BYTES`. `manage.py dbs upgrade --backups DIR`
converts them: each one is written to a new `NAME.v2.dbs` beside it, readable by its owner
alone, and validated end to end before it takes that name. The original is never touched.
Nothing in DBS deletes or overwrites a backup.

## Security model

- **Encryption.** Argon2id derives a key from the passphrase, and AES-256-GCM encrypts the
  payload under a random data key wrapped by it. The file never holds the passphrase or the raw
  data key. New backups use a time cost of 3, 64 MiB of memory and a parallelism of 4 by
  default. A format 2 backup that asks for a time cost above 10 or more than 256 MiB of memory
  is refused before any work, so a crafted file cannot tie up the machine that reads it.
- **A wrong passphrase** fails authentication before any data is produced; it never yields
  partial or garbage data.
- **Files on disk.** Every local backup, and every temporary file it is written through, is
  readable by its owner alone from the first byte. An SFTP upload is too, before its bytes
  arrive.
- **Passphrases in transit.** A panel job's passphrase reaches its child process on standard
  input, never in its arguments or its environment. The manager hands an application's
  passphrase to the project on standard input too.
- **The manager's secrets.** Every server credential, passphrase, `.env` version and archive
  in the manager is sealed with AES-256-GCM under its sealing key, kept in the system keychain
  where one works, and never returned by any page or API.
- **Remote commands.** SSH host keys are verified by default, and the manager pins exactly the
  key a person confirmed. Remote commands are built from fixed argument lists, and passphrases
  travel on standard input, never on a command line. Deploy steps come from a fixed list; no
  command line is taken from a request.
- **Discovery** runs nothing in a folder, or a project below it, that another account can write
  to, and reads nothing from a container's environment but `DJANGO_SETTINGS_MODULE` and the
  virtualenv folders on its `PATH`.
- **The terminal** is for admins, asks for the account password for every shell, closes on
  sign-out or a password or role change, and records no keystroke or output. The console and
  the MCP server never reach it.
- **`sudo`** is used only by a server move, to prepare the new server. The password is typed
  per move and travels on standard input only.

[SECURITY.md](../SECURITY.md) has the reporting process and the full threat model.

## Observability

DBS logs to the `dbs` logger, including a `WARNING` whenever damage was detected and healed;
route it somewhere you will see it. The panel's **Health** page and `manage.py dbs health
--json` report the state of a project's backups, and the audit trail records every backup,
restore and change. The manager writes `manager.log` in its data folder, and its **Activity**
page is its own audit trail.
