# activity

The activity list: every action DBS Interface records — a server added, edited, deleted,
checked, its host key fetched or pinned, its backup passphrase shown, a sign-in, a refused
sign-in, a sign-out, a backup taken, run by a plan, uploaded, verified, downloaded, deleted or brought back,
old backups deleted after a run, deleted backup files removed, a backup plan added, edited or
deleted, a file downloaded, uploaded or deleted on a server, a folder created there, a server's
.env file pulled, its values shown or a version of it pushed back — newest first, with its status,
who did it and from where. Read-only: an entry has no actions. A slice that records a new action
code on the backend adds it to `ACTIVITY_ACTIONS` and to both bundles under `activity.actions.*`,
as `backups` did for `backup.*` and `plan.*`, `files` for `files.*` and `envfiles` for `env.*`.

Built with PrimeNG 22 and the shared facades: `p-card`, `p-select` inside `<app-field>`,
`p-message`, `pButton`, `p-skeleton`, `<app-empty-state>`, `p-table`, `p-tag`, `p-paginator`, and
the `appDate` pipe. The page opens no dialogs.

## Routes and guard

```
/activity                        ActivityPage   every server; page title and subtitle
/servers/:serverId/activity      ActivityPage   that server only; a tab of the server page
```

`activity.routes.ts` is mounted twice: in `app.routes.ts` under `AppLayout`, with a `SECTIONS`
entry in `core/layout/app-layout` (icon `fa-heart-pulse`), and as a lazy child of `:serverId` in
`features/servers/servers.routes.ts`, with a tab in the server page's `TABS`. The slice's root
route carries `activityGuard`, `ActivityStore` and the bundles. Each mount loads the routes on its
own, so each has its own `ActivityStore`.

`activityGuard` is "signed in" — it mirrors `IsAuthenticated` on `/api/activity/`. The backend
permission is the boundary (rule 21); narrowing the list to a group is a change to both.

## Backend counterpart

`backend/apps/activity/`. One endpoint:

| Method | Path | Store call |
|---|---|---|
| GET | `/api/activity/?server=&action=&status=&page=&page_size=` | list resource (`open`, `setStatus`, `setAction`, `clearFilters`, `goToPage`, `reload`) |

Newest first, paginated. A filter left empty is not sent. `data/activity.types.ts` mirrors the
serializer in `backend/apps/activity/serializers/`; the two move together.

## The contract

`ActivityStatus` is where a recorded action stands: an instant action is recorded `succeeded` or
`failed`; a job moves `queued` → `running` → one of those. `ACTIVITY_STATUSES` lists them in that
order, which is also the order the status filter offers.

`ActivityEntry` is one row. `action` is a dotted code (`server.check`, `auth.sign_in`), never prose.
`target` is what the action was on — a name, a path, a username, never a secret — or `''`.
`detail` holds small non-secret facts. `error_code` is why it failed (`ssh_unreachable`, …) or `''`.
`ip` is `null` for work no request started. `actor` is `null` when nobody signed in did it: a
scheduled job or a refused sign-in. `server` is `null` when the action was on no server or the
server has since been deleted; `server_name` is the name as recorded and outlives the server.

`ActivityQuery` is the query string; a filter left out is not sent, and `page` is one-based, as DRF
counts.

## The store

One `ActivityStore`, route-provided — and, because the routes are mounted twice, one per mount.
Writable state: `server` (`null` for every server), `status` (`''` for every status, typed
`ActivityStatusFilter` in `state/activity.store.types.ts`), `action` (`''` for every action), `page`
(zero-based; a `linkedSignal` that resets to 0 when any of the three changes), `pageSize` (one of
`ACTIVITY_PAGE_SIZES`, the first being the default).

Loaded with `rxResource`; params are `undefined` until the page calls `open(server)`, so the list
loads only while it is on screen. `open` also clears the filters and the page: a route's injector
outlives the page, so without it a second visit — or another server's tab — would start with the
last visit's filters.

While the next page or the next filter loads, the previous result stays up rather than the table
blinking to a skeleton; once the list closes, nothing is kept.

`computed`: `entries` (a mutable copy, as `p-table` takes), `count`, `error`, `pending` (nothing to
show yet), `empty` (loaded with no rows), `filtered` (a status or an action is set; the server scope
is not a filter). `loading` is the resource's `isLoading`. Errors are the `ApiError` the interceptor
produced; the page resolves `error.code` through `errorText`.

## Classes and methods

**`ActivityApi`** — transport for `/api/activity/`. `list(query)` fetches one page, newest first,
with only the filters that are set on the query string.

**`ActivityStore`** — the list as signals: scope, filters, page and the backend's answer.
- `open(server)` starts listing, about one server or every one, with no filter set and on the first page.
- `close()` stops listing and forgets the rows.
- `setStatus(status)`, `setAction(action)` narrow the list; `clearFilters()` clears both.
- `goToPage(page, pageSize)` moves to a zero-based page at a page size.
- `reload()` asks again after a failure.

**`ActivityPage`** — the list on screen, global or scoped to the server in its route.
- `actionLabel(code)` names an action, or returns the code for one the bundles do not have.
- `look(status)` is the tag severity and Font Awesome icon for a status.
- `scheduled(entry)` reads an entry with no actor as scheduled work, except an account action.
- `onStatus`, `onAction`, `clearFilters`, `onPaged`, `retry` pass the reader's intent to the store.

**`activityGuard`** — anyone signed in may open the list; its own guard so a later narrowing to a
group is a change here and in the backend permission only.

## Decisions

**The page reads its scope from the route.** `/servers/:serverId/activity` sets the server; the
router's default param inheritance stops at the server page (a route with a component), so the
page walks `pathFromRoot` to the route that declares `:serverId` and follows its `paramMap`.
Scoped, it drops the title band (the server frame names the page, as on the overview tab), leaves
out the server column (`@if` around its `th` and `td`), and leaves the `auth.*` actions out of the
action filter, since none of them is about a server.

**An unknown action code renders as itself.** `ACTIVITY_ACTIONS` in `data/activity.types.ts` is the
list the filter offers; an entry with a code the bundles do not have yet shows the code, so a
backend that records a new action first never breaks the page.

**Error codes resolve through `errorText`.** The SSH codes a recorded failure carries
(`host_key_changed`, `ssh_auth_failed`, `ssh_unreachable`, `remote_command_failed`,
`invalid_host_key`) live in `core/i18n`, not in the servers bundle, so `/activity` resolves them
without the servers route ever having loaded. A code no bundle has reads as `errors.generic`.

**A failed entry's reason sits under its status tag**, as a second line in the same cell, rather
than in an expandable row offered on every entry.

**A status is never colour alone.** Each `p-tag` carries its word and an icon: `fa-clock` queued,
`fa-spinner` running, `fa-circle-check` succeeded, `fa-circle-xmark` failed.

**No actor means two things.** For an `auth.*` entry it is a sign-in that was refused — shown as
a dash. For anything else it is scheduled work — shown as "Scheduled task".

**A server that has been deleted** arrives as `server: null` with `server_name` kept: the name is
shown, not linked, with "Deleted" beside it. With neither, the cell is a dash.

**Paging is a `p-paginator` beside a plain `p-table`**, inside a `<nav>` named by
`activity.list.pages`. The table only ever holds the one page the store loaded; the paginator's
`first` is derived from the store's zero-based `page` and `pageSize`, and its `onPageChange` goes
back through `goToPage`. The table's own paginator has no way to name its landmark. The
paginator's digits are Latin in both languages (`locale="en-US"`).

**The table's accessible name** comes through PrimeNG's pass-through (`table: { aria-label }`),
since `p-table` has no label input.
