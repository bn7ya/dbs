# servers

The servers DBS Interface reaches over SSH: list them, add one with its host key pinned, check
that it answers and has django-dbs, edit its settings, re-pin a changed host key, show its backup
passphrase, delete it. Every later per-server slice (backups, files, environment, activity) hangs
a tab off the server page this slice builds.

## Routes and guard

```
/servers                      ServersPage          list, search, paging, add
/servers/:serverId            ServerPage           frame: name, address, status, tab row
/servers/:serverId (child '') ServerOverviewPage   check, settings, host key, passphrase, delete
/servers/:serverId/backups    (backups slice)      that server's backups — `features/backups`
/servers/:serverId/files      (files slice)        its allowed folders' files — `features/files`
/servers/:serverId/environment (envfiles slice)   its .env file's versions — `features/envfiles`
/servers/:serverId/activity   (activity slice)     that server's activity — `features/activity`
```

Mounted under `AppLayout` in `app.routes.ts` (behind its `authGuard`). The slice's root route
carries `serversGuard`, `ServersStore` and the bundles. Each sibling slice's child route is a lazy
entry to that slice's own routes, guard, store and bundles; its page reads the server from
`:serverId`.
`serversGuard` is "signed in" — it mirrors `IsAuthenticated` on every `/api/servers/` view. The
backend permission is the boundary (rule 21); narrowing this to a group is a change to both.

## Backend counterpart

`backend/apps/servers/`. Endpoints, all under `/api/servers/`:

| Method | Path | Store call |
|---|---|---|
| GET | `?search=&page=&page_size=` | list resource (`openList`, `setSearch`, `goToPage`) |
| POST | `` | `create` |
| GET | `{id}/` | server resource (`select`) |
| PATCH | `{id}/` | `update(id, changes)` — no host key, no backup passphrase; `account_password` when more than the name changes |
| DELETE | `{id}/` | `remove` (soft delete on the backend) |
| POST | `fingerprint/` `{host, port}` | `fetchHostKey` — pins nothing |
| POST | `{id}/check/` | `check` — synchronous, tens of seconds |
| POST | `{id}/host-key/` `{host_key, password}` | `repinHostKey` |
| POST | `{id}/passphrase/` `{password}` | `revealPassphrase` |

Error codes this slice owns live in its own bundle under `errors.*`: the three the form produces
itself (`port_range`, `host_key_missing`, `host_key_unconfirmed`). The SSH codes its operations
fail with — `host_key_changed`, `ssh_auth_failed`, `ssh_unreachable`, `remote_command_failed`,
`invalid_host_key` — are in `core/i18n` with the other shared codes (`required`,
`invalid_password`, …), because the activity list shows them too, at `/activity`, where this slice's
bundle has never loaded. `name_taken` and `absolute_path_required` are there as well, since the
backups plan form shows both: bundles merge into one dictionary, so a code two features show has
one text. The backend's `absolute_path_required` also covers a `..` step; this form checks only the
leading `/`, so a `..` is caught on save.

## The store

One `ServersStore`, route-provided. Writable state: `search`, `page` (a `linkedSignal` that
resets to 0 on a new settled search), `pageSize`, `saving`, `fetchingHostKey`, `checking`,
`repinning`, `revealing`, `deleting`, and one `ApiError | null` per operation (`saveError`,
`hostKeyError`, `repinError`, `revealError`, `deleteError`). `checkError` and `passphrase` are
`linkedSignal`s on the selected id, so showing another server clears them.

Loaded with `rxResource`: the list (params `undefined` until `openList()`, so it loads only
while the list page is on screen and fresh each time it opens) and the selected server.

`computed`: `servers`, `count`, `listLoading`, `listError`, `listPending`, `searching`,
`listEmpty`, `server`, `serverLoading`, `serverError`, `serverMissing`, `checkFailure` (the code
of the check just run, else the failure the row records), `hostKeyChanged`.

## Decisions

**Components are PrimeNG** (`primeng/*`) through the shared facades: `Dialogs`, `Confirmation`,
`Toaster`, `<app-field>`, `<app-password-input>`, `<app-empty-state>`, `appDate`. Buttons are the
`pButton` directive on a native `<button>` or `<a>`; a busy button is `[disabled]` plus a spinner
glyph, since the button and password components are deprecated in PrimeNG 22.

**Dialogs share the route's store.** `ServerForm` and `HostKeyReview` inject `ServersStore`. The
pages that open them list `providers: [Dialogs]`, so a dialog resolves the route's
providers; the dialog frame renders the title from `titleKey`, and the body is a
`form.dialog-form` ending in `.dialog-actions`. `ServerForm` opens at `size: 'lg'`. `PasswordPrompt` is generic and gets the
operation and its error signal through its data instead; it lives in `shared/password-prompt`, since
the envfiles slice asks for the password the same way, and its two strings (`password.*`) are in
`core/i18n`. `HostKeyReview`'s own password field reads the same two.

**The password prompt runs the operation.** A wrong password is said under the field and the
reader retries in place; handing the password back would close and reopen the dialog per try.

**The list keeps its rows while the next page or search loads**, and forgets them when the list
closes, so a deleted server never flashes back. Search settles for 300 ms (an RxJS `debounceTime` into a signal).

**Paging is a `p-paginator` in a labelled `<nav>` beside a non-lazy `p-table`**, the same shape
the activity slice uses: the store's zero-based `page` and `pageSize` stay the contract, and the
page turns `first`/`rows` into them. The table's accessible name goes on through `pt`.

**The server page's tab row is a `<nav>` of `a[pButton]`** with `routerLinkActive`: secondary and
filled when active, text otherwise, with `aria-current="page"`. A tab is a route, so it is a real
link. A slice adds a child route under `:serverId` and one entry to `TABS` in
`pages/server/server.ts`. A tab is active on an exact path with the query ignored (`TAB_MATCH`):
the files tab keeps its folder in `?path=`. The overview's path is `.`, since an empty link resolves
to the application's root.

**The add/edit form is a PrimeNG `p-stepper`.** Step values count from 1 because PrimeNG prints the
value as the step's number. The stepper is not `linear`: adding a server opens a step header only
once every step before it is done (`stepOpen`), and a done step shows a check glyph. `allowed
folders` is a `p-inputtags`; it has no `inputId`, so the field's id and description reach its input
through `pt`.

**Host keys.** Adding a server needs a fetched key and a ticked "fingerprints match"; changing
host or port drops the fetched key. The compare command matches the key type
(`ssh_host_<type>_key.pub`). Re-pinning goes through `HostKeyReview` and the reader's password.

**An edit that changes more than the name asks for the reader's password.** Where the server is,
how it is signed in to, what runs there and what is read there are what a stolen session would
change, so the backend refuses them without `account_password`. The form compares what it would send
with what the server has (`needsPassword`, secrets typed included) and shows "Your password" at the
foot of the last step only then; a rename sends none. A wrong password is said under that field, not
above the form; if the backend asks for one the form did not expect, the field shows anyway.

**Secrets are write-only.** The form starts every secret empty; on an edit an empty secret is
not sent, and the hint says it is kept. Only the chosen sign-in method's secrets are sent.

**The backup passphrase is not editable.** It encrypts backups already made, so changing it is
not an edit; it is set (or generated) once, on create.

**Technical values are monospace** (`--app-font-mono`) where they are our own elements: addresses,
fingerprints, commands, paths. PrimeNG inputs holding a key, a path or the revealed passphrase keep
the theme's family; restyling them would be a `.p-*` override.

**Names inside a plain string** (the delete confirmation title) are wrapped in FSI…PDI so a
Latin name keeps its direction inside the Arabic sentence.

## Contract notes

Secrets travel one way. A private key, key passphrase, server password and backup passphrase are
written by `ServerCreate` / `ServerUpdate` and never read back: `Server` says only whether one is
saved (`has_*`). On update, an empty or absent secret keeps the stored one. The backup passphrase is
read only through its own endpoint, behind the reader's password. `ServerUpdate.account_password`
is required once anything but the name changes; a field sent with its current value is not a
change. `last_check_error` is a code or `''`, never prose.

`CheckStatus`: `unknown` never checked; `ok` connected and found everything; `problem` connected
but something is missing; `failed` did not connect or the host key did not match. `CheckReport`
keys are all optional, and `null` means the check could not look (`env_file` is `null` when no
`.env` path is set). `HostKey.line` is the `known_hosts` line to pin; `fingerprint` is the
`SHA256:` form `ssh-keygen -lf` prints. The list query's `page` is one-based, as DRF counts.

## Classes and methods

**`ServersApi`** — transport for `/api/servers/`, one method per endpoint, no state. `fingerprint`
connects, reads the presented host key and pins nothing; `check` answers once the check has
finished, which can take tens of seconds.

**`ServersStore`** — the slice's state, route-provided so the list page, the server page and every
dialog share one instance. `openList`/`closeList` load the list only while its page is on screen;
`setSearch`, `goToPage`, `reloadList` drive it. `select(id)` shows a server (or nothing) and
`reloadServer` reloads it. `resetForm` and `resetHostKeyReview` clear what an earlier dialog left.
`create` and `update` resolve with the server as saved or `null` with `saveError` set;
`fetchHostKey` reads a presented key; `check` runs the connection check and reloads the row either
way; `repinHostKey(line, password)` pins a key; `revealPassphrase(password)` and `hidePassphrase`
show and clear the passphrase; `remove` soft-deletes the server on screen. `SERVER_PAGE_SIZES` is
what the list offers, the first the default.

**`serversGuard`** — who may open `/servers`: anyone signed in, mirroring `IsAuthenticated`.

**`ServersPage`** — `/servers`: the searchable, paged list and the way in to adding a server.
`add()` opens `ServerForm` and goes to the new server.

**`ServerPage`** — `/servers/:serverId`: the frame with the name, address, last check and tab row
over the child route. `retry()` reloads the server.

**`ServerOverviewPage`** — the overview tab: the check first, then settings, host key, backup
passphrase and delete. `check`, `edit`, `reviewHostKey`, `togglePassphrase`, `copy` and `remove`
each run one of those; `look(presence)` gives the glyph for a check result.

**`ServerForm`** — adds or edits a server in steps; each error code sits under its field and the
step holding the first one opens. `advance` moves on or saves on the last step, `back` steps back,
`update` changes one draft field (and drops a fetched key when host or port changes),
`fetchHostKey` fetches the presented key, `error(field)` is the code to show,
`stepReady`/`stepDone`/`stepOpen` say whether a step has nothing to fix, has been passed, and can be
opened. Closes with the saved server.

**`HostKeyReview`** — the pinned key beside the presented one; pins the new key once the reader
ticked the match and gave their password. `fetch` re-reads the presented key, `pin` pins it.
Closes with `true` once pinned.

**`HostKeyFacts`** — a host key's type and fingerprint as selectable technical values; with
`compare`, also the `ssh-keygen -lf` command for the key file that matches the type.

**`CheckStatusTag`** — the last check's outcome as a `p-tag`: a glyph, a word and a severity.

