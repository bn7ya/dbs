# envfiles

One server's `.env` file and the versions DBS Interface keeps of it: pull the file now (a new
version only when it changed), list the versions newest first, select one to see its key names
with every value masked, compare it with the version before it, show its values with the reader's
password — copy them, download them as a file, hide them — and push it back to the server. A tab of
the server page.

## Route and guard

```
/servers/:serverId/environment    EnvfilesPage    a tab of ServerPage (features/servers)
```

Mounted as a lazy child of `:serverId` in `features/servers/servers.routes.ts`, with a tab in the
server page's `TABS` (Overview, Backups, Files, .env file, Activity). The route path is
`environment`; the tab and the page title are ".env file" / «ملف متغيرات البيئة», the name the
server's settings already give the concept (language.md rule 10). The slice's root route carries
`envfilesGuard`, `EnvfilesStore` and the bundles. Both empty states use the Font Awesome `fa-key`
glyph.

`envfilesGuard` is "signed in" — it mirrors `IsAuthenticated` on `/api/envfiles/`. The backend is
the boundary (rule 21): it also asks for the reader's password before it sends a value or writes
the file. Nothing here decides who may see a value.

## Backend counterpart

`backend/apps/envfiles/`. Endpoints:

| Method | Path | Store call |
|---|---|---|
| GET | `/api/envfiles/?server=&page=&page_size=` → `Page<EnvVersion>` | list resource (`open`, `goToPage`, `reload`) |
| POST | `/api/envfiles/pull/` `{server}` → `{created, version}` | `pull` |
| GET | `/api/envfiles/{from}/compare/?to={to}` → `{from, to, added, removed, changed}` | `compare` |
| POST | `/api/envfiles/{id}/reveal/` `{password}` → `{content}` | `reveal(version, password)` |
| POST | `/api/envfiles/{id}/push/` `{password}` → `{version}` | `push(version, password)` |
| GET | `/api/servers/{id}/` — only `env_path` is read | path resource (`envPath`, `noPath`) |

The servers read lives in `EnvfilesApi` because a feature never imports another feature (the
backups slice reads `/api/activity/` the same way). `GET /api/envfiles/{id}/` has no caller: a list
row already carries everything the detail shows.

**Compare direction.** The page compares the selected version (`to`) with the one kept before it
(`from`), so `added` is what the selected version has that the older one did not. `changed` comes
from the backend comparing the values, so two versions with the same key names can still differ.

Codes: `env_path_missing` (400) and `env_too_large` (413) are in `core/i18n`, beside the remote and
SSH codes a pull or a push fails with, because `/activity` lists failed `env.*` entries without this
bundle loaded. `invalid_password` is core's too. The three actions — `env.pull`, `env.reveal`,
`env.push` — are in `ACTIVITY_ACTIONS` and the activity bundles.

## The store

One `EnvfilesStore`, route-provided. The route's injector is shared by every server and outlives
the page, so the page calls `open(server)` / `close()`, and a pull is keyed by server.

Writable: `server`, `page`, `pageSize`, `revealError`, `pushError`, and the private `chosen` (the
picked version's id), `pullingOn` (servers), `comparingId`, `comparisonState`, `compareFailure`.
`revealed` is a `linkedSignal` on the selected id: another selection — picked, or the list moving
under it — resets it to `null`. Both the list and the server's path load with `rxResource`; params
are `undefined` until `open`.

`computed`: `envPath` (`''` when unset, `null` while unknown), `noPath`, `versions`, `count`,
`error`, `pending`, `empty`, `selected` (the picked version when it is on the page, else the first
row), `hasPrevious`, `content`, `comparison`, `compareError`, `comparing`, `pulling`. `loading` is
the list resource's `isLoading`. `shown` (a `linkedSignal`) keeps the previous page of the same
server while the next one loads, with the query that loaded it, so a version's place in the whole
list is known.

## Decisions

**A value reaches the browser only on request, and leaves as soon as it can.** The list and the
comparison are key names. `reveal` fetches the whole content with the reader's password, through the
shared `PasswordPrompt`; the content lives in the store's `revealed` signal and nowhere else, and it
is cleared on Hide, on selecting another version, on moving to another page, after a pull or a push
selects the new version, and on leaving the tab (`DestroyRef` → `close()`). Content that arrives
after the reader moved on is dropped, never shown beside the wrong version.

**Download is a real link to a `blob:` URL.** An effect creates the URL when content is on screen
and revokes it in its cleanup — when the content goes or the page is destroyed — so no timer is
needed to release it (rule 10). The file is named after the version's path, `.env` when it names no
file. Copy goes through `navigator.clipboard` (read from `DOCUMENT`), with a toast either way; with no
clipboard the toast says to select and copy by hand.

**The previous version.** The next row on the page; for the last row on a page, the one row after it
read on its own (`page_size=1`, `page` = its place + 1). The oldest version offers no Compare and
says it is the first version kept.


**Selecting is a button in the When cell**, labelled with the date: filled `secondary` with
`aria-current="true"` for the version on screen, `text` otherwise — the same signifier the server
page's tab row uses. It is a `button[pButton]`, so `aria-current` is a plain attribute binding.
`p-table`'s selection mode would draw a radio or checkbox and let the reader clear the selection,
leaving no version to show.

**Buttons are the `pButton` directive** (`ButtonDirective`), never `p-button`, which PrimeNG 22
deprecates. A running pull or compare is `[disabled]` + `aria-busy` with a leading spinner glyph. The
links to Overview and the download are `a[pButton]`.

**The table pages on the server.** `p-table` with `[lazy]`, `[paginator]` (only past the smallest
page size), `[rows]`, `[first]`, `[totalRecords]`, `[rowsPerPageOptions]` and `(onPage)`;
`onPage` turns `first / rows` into the store's zero-based `page` and `pageSize`. The table's
`aria-label` and the paginator's `role="navigation"` + label go in through `[pt]`.
`paginatorLocale="en-US"` keeps page numbers in Latin digits in both languages.

**Master and detail.** Both cards have a flex basis of `$card-max` (`_layout.scss`), the list
growing 3 to the detail's 2; when the two do not fit side by side they stack, the list first.

**Pull answers either way.** "New version kept." (success, the new version selected on the first
page) or "No change since the last version." (info, nothing reloads). The store raises the toasts
through `Toaster`, since a pull can end after the reader has left the tab. Pull now sits beside the
title; it is hidden while the empty state offers it and when the server has no `.env` file set. While
it runs its label reads "Pulling…".

**Push asks twice.** `Confirmation.ask` names the file it replaces (the server's path, LRI…PDI,
because the confirm dialog takes a plain string) and says the current file is kept as a version
first; then the password prompt runs the push. On success the pushed version is selected on the
first page. Push is hidden when the server has no `.env` file set. `push` and `reveal` take the
version they act on, so the prompt cannot act on another one.

**Dialogs.** The page lists `providers: [Dialogs]` so `PasswordPrompt` resolves the
route's `EnvfilesStore`. It opens with `Dialogs.open(PasswordPrompt, { titleKey, data, size: 'sm' })`;
the frame renders the title from `titleKey`, the same key the prompt data carries.

**No path set.** With no version kept, the card is the empty state with a link to the server's
Overview. With versions kept, they stay listed, showable and comparable, under a warning that says
the path is not set, with the same link.

**Direction.** Paths, key names and the content box carry `dir="ltr"` on the content element only
(rule 22c); the taker's name is isolated with FSI…PDI inside the translated "By {name}".

**The content box** is a read-only `textarea[pTextarea]` inside `<app-field>`, `rows` clamped from
the content's line count to 4…20 (PrimeNG's `autoResize` has no maximum). Paths, key names and the
box itself take `var(--app-font-mono)` through the slice's own `.envfiles__code` class.

## Data shapes

`data/envfiles.types.ts` mirrors `backend/apps/envfiles/serializers/`. A version (`EnvVersion`) is one
state of the file, kept encrypted: `path` absolute on the server, `size` in bytes, `keys` the variable
names in file order (never a value), `source` — `pulled` (by hand, or the file a push replaced),
`pushed` (what a push wrote), `scheduled` (the daily snapshot) — and `taken_by`, `null` for the
snapshot. `EnvListQuery.page` is one-based, as DRF counts. `PullResult.created` is `false` when the
file is already the newest version, which is then `version`. `EnvComparison` carries key names only:
`added` (in `to`, not `from`), `removed`, `changed` (both, different values). `ServerEnvPath.env_path`
is `''` when unset. `state/envfiles.store.types.ts` and `pages/envfiles/envfiles.types.ts` hold the
store's and the page's private shapes.

## Classes and methods

**`EnvfilesApi`** — transport for `/api/envfiles/` plus the one read of `/api/servers/{id}/`; one
method per endpoint, no state. `list(query)` one server's versions, newest first. `pull(server)`
keeps the file as a new version unless unchanged. `compare(from, to)` what changed, key names only.
`reveal(id, password)` a version's whole content. `push(id, password)` writes a version to the
server. `envPath(server)` where the server's file is, `''` when unset.

**`envFileName(path)`** — the name a revealed version downloads under: its path's base name, or `.env`.

**`envfilesGuard`** — anyone signed in; mirrors `IsAuthenticated` on `/api/envfiles/`. Its own guard
so narrowing the page to a group is a change here and in the backend permission only.

**`EnvfilesStore`** — one server's `.env` file as signals. `open(server)` starts showing a server from
the first page, newest selected; `close()` drops the content when the page leaves. `goToPage(page,
size)` and `reload()` move and refresh the list. `select(version)` shows another version and drops
what was shown of the last. `reveal(version, password)` fetches the content, resolving `true` or
`false` with `revealError`; `hide()` takes it out of memory. `compare()` compares the selected version
with the one before it. `pull()` keeps the file as a new version and toasts either way. `push(version,
password)` writes a version back, resolving `true` with it selected or `false` with `pushError`.
`ENV_PAGE_SIZES` are the page sizes offered, the first the default.

**`EnvfilesPage`** — `/servers/:serverId/environment`: the versions card and the selected-version
card. Reads `:serverId` from the route that declares it (param inheritance stops at the server page).
`select`, `pull`, `compare`, `retry` hand intent to the store; `toggleValues(version)` hides the values
or opens the password prompt to show them; `copy(content)` copies with a toast either way;
`push(version)` confirms, then opens the password prompt; `onPage(event)` maps the table's page event
to the store; `takenBy(version)` is "By {name}" or `null`. `downloadHref` is the `blob:` URL of the
content on screen.
