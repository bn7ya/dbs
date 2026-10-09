# files

One server's files, inside the folders its settings allow (`file_roots`): open a folder, go back
up through the breadcrumb, switch between allowed folders, upload a file into the folder on
screen, create a folder, download a file, delete a file or an empty folder. A tab of the server
page.

## Route and guard

```
/servers/:serverId/files?path=<abs>    FilesPage    a tab of ServerPage (features/servers)
```

Mounted as a lazy child of `:serverId` in `features/servers/servers.routes.ts`, with a tab in the
server page's `TABS` (Overview, Backups, Files, Activity). The slice's root route carries
`filesGuard`, `FilesStore` and the bundles. Every glyph is Font Awesome, written in the template.

`filesGuard` is "signed in" — it mirrors `IsAuthenticated` on `/api/files/`. The backend permission
is the boundary (rule 21), and so is its path check: every path is resolved on the server and
refused with `path_outside_roots` outside the allowed folders. Nothing here decides what may be
read; the page only lists what the backend answered.

## Backend counterpart

`backend/apps/files/`. Endpoints, all under `/api/files/{server}/`:

| Method | Path | Store call |
|---|---|---|
| GET | `?path=&page=&page_size=` → `Listing` (`Page<Entry>` + `path`, `parent`, `root`, `roots`) | listing resource (`show`, `goToPage`, `reload`) |
| GET | `download/?path=` | `downloadUrl` — a link, not a request |
| POST | `upload/` multipart `path` (the folder), `file` → 201 `Entry` | `uploadFile(folder, file)`; `cancelUpload` aborts |
| POST | `folders/` `{path, name}` → 201 `Entry` | `createFolder(folder, name)` |
| DELETE | `?path=` → 204 | `remove(entry)` |

Without `path` the listing is the first allowed folder. Codes: `no_allowed_folders` (400, the
server has none), `path_outside_roots` (403), `file_exists` (409, upload or new folder),
`folder_not_empty` (409), `cannot_delete_root` (400), `not_a_file`, `upload_too_large` (413), the
remote ones (`remote_not_found`, `remote_permission_denied`, `remote_command_failed`) and the SSH
ones. Every one of them lives in `core/i18n`: the backend records `files.*` actions in the
activity log, and `/activity` shows a failed entry's code without this bundle loaded. The four
actions — `files.download`, `files.upload`, `files.create_folder`, `files.delete` — are in
`ACTIVITY_ACTIONS` and the activity bundles.

## The store

One `FilesStore`, route-provided. The route's injector is shared by every server and outlives the
page, so the page calls `show(server, path)` / `close()`, and an upload is keyed by server.

Writable: `server`, `requested` (the `?path=`, `null` for the first allowed folder), `page` (a
`linkedSignal` that resets to 0 on another server or folder), `pageSize`, `creating`,
`createError`, and the private `uploads` (`{server, folder, name, sent, total}`, one per server)
and `deleting` (keys of server and path), with each upload's `Subscription` in a plain `Map` — a
handle for Cancel, not state on screen. `Upload` and the two `linkedSignal` source shapes live in
`state/files.store.types.ts`. The listing loads with `rxResource`; params are
`undefined` until `show`.

`computed`: `entries`, `count`, `error`, `pending`, `empty`, `noFolders` (the error is
`no_allowed_folders`), `current` (the folder listed on screen — where an upload or a new folder
goes, `null` while none is), `roots`, `folder` (on screen, or being opened), `root`, `trail` (the
`Crumb`s from the root down), `upload`, `uploading`, `uploadProgress`. `loading` is the resource's
`isLoading`. `isDeleting(entry)` reads `deleting`.

`trailOf`, `rootOf` and `folderNameProblem` in `data/files.types.ts` are plain functions with their
own spec.

## Decisions

**The folder is in the URL.** `?path=` on the files route, so Back returns to the folder before,
a reload stays where it was, a folder opens in a new tab, and the sign-in redirect comes back to
it. A folder's name in its row is a plain `<a>` with `[routerLink]="[]"` and the path as its query
(so a long name wraps in its cell); each crumb is the same kind of link, and the root picker
navigates to the same URL. The store never
navigates: it lists what the page reads from the URL. The server page's tabs match on the path
only (`TAB_MATCH`, query ignored), or the Files tab would stop looking current inside a folder.

**The way up is the breadcrumb.** `p-breadcrumb` with an `#item` template: the allowed folder in
full with the `fa-folder` glyph, then one crumb per folder below it; the last is the folder on
screen, a `span` with `aria-current="page"`, the others router links carrying PrimeNG's
`p-breadcrumb-item-link` class so they look like its own items. The trail's `aria-label` goes on
its `nav` through `pt`. There is no separate Up button. PrimeNG's breadcrumb does not fold a long
trail; it scrolls inline. While another folder loads, the trail already names it (from `requested`
and the server's known roots), so a click answers at once; its rows wait under a skeleton. Another
folder's rows are never kept, since they would sit under the wrong place. Another page of the same
folder keeps its rows until the next arrives.

**Names render in their own direction** (rule 22c). Every folder and file name — in a row, a
crumb, a root option (`p-select` `#item` and `#selectedItem` templates), the upload line — is a
`<bdi dir="auto">`, the direction on the content element only; the breadcrumb follows the page's
direction and PrimeNG mirrors its chevrons. The two places a path is a plain string inside text —
the confirmation's message and the new folder dialog's "created in" line — wrap it in LRI…PDI.

**The roots are read before anything else in `root`.** A `linkedSignal` keeps only the value it
last computed; `roots` has to be computed while a listing is on screen to still be there while the
next folder loads. The store spec reads the state the page draws (`look()`) for the same reason.

**Focus follows a folder.** Opening a folder replaces the rows, and with them the link that had
focus; `afterRenderEffect` puts focus on the location block (`tabindex="-1"`), which reads out
where the reader now is. It moves focus only when it had fallen to the document.

**What opens and what does not.** A folder opens. A file downloads (an `<a pButton variant="text" size="small">` with `download`, same-origin, the browser streams it). A `link` is listed as itself and never followed, and an
`other` (socket, pipe, device) is neither: both show their glyph and a `secondary` `p-tag` under the name
("Link", "Special file"), and no Open or Download. Delete is offered on every row; the backend
decides (`folder_not_empty`, `cannot_delete_root`, `path_outside_roots` for a link that leads
outside). Row glyphs are Font Awesome — `folder`, `file`, `link`, `file-circle-question` —
decorative beside the name.

**Delete asks first, and there is no undo.** `Confirmation.ask` titled "Delete this file?" or "Delete this
folder?", the full path as its message (LRI…PDI), and a detail that says it cannot be undone — a
folder's says only an empty one can be deleted. The store toasts the outcome through `Toaster`
(summary, and the file's name in `detail`, isolated with FSI…PDI). When the deleted row
was the only one on a later page, the page before it is shown instead of a page that no longer
exists.

**Upload is the backups upload.** Same hidden native picker behind a `secondary` `<button pButton>` (busy: disabled, `aria-busy` and a spinner glyph), same
two phases on screen (a determinate `p-progressbar` with Cancel while bytes are sent, then an
indeterminate one under "Saving the file on the server…" with nothing to cancel; the visible line
labels the bar through `aria-labelledby`), same `withXhr()` dependency. The file goes into the
folder on screen when it was chosen; if the reader has opened another folder by the time it is
written, the listing on screen is left alone and the toast still says it was uploaded. A `fields.file` or
`fields.path` code is the toast itself. No `accept`.

**Upload and New folder need a folder on screen.** They are `disabled` while none is listed —
loading another folder, or after a failure — and hidden altogether when the server has no allowed
folders, where the card is the empty state with a link to the server's Overview.

**The new folder dialog checks the name the way the backend does** (`folderNameProblem`):
something other than spaces, no `/` or `\`, neither `.` nor `..`, surrounding spaces trimmed, at
most 255 characters (`maxlength`). It says so under the field once the reader has tried, and as
they correct it. `file_exists` and any `fields.name` code from the backend go under the field too;
anything else is a `p-message` above it. The field is `<app-field>` around a `pInputText` with
`appFieldControl`. The input is `dir="auto"`: a folder's name is written in its own direction.
The dialog injects the route's `FilesStore`: the page lists `providers: [Dialogs]`,
so `Dialogs.open(NewFolderDialog, { titleKey: 'files.newFolder.title', data: { folder }, size: 'sm' })`
resolves the page's route-level providers. The frame draws the title; the body is
`form.dialog-form` with its buttons in `.dialog-actions`, Cancel closing with nothing.

**Sizes** are the shared `fileSize` pipe (`shared/file-size`), decimal and in the application's
language; a folder's size is a dash. Dates are the shared `appDate` pipe. The table is `p-table`
with `[lazy]` and its own paginator (`[first]`, `[rows]`, `[totalRecords]`, `(onPage)` mapped back
to the store's zero-based `page` and `pageSize`), shown only past the smallest page (50). It has no
narrow-screen card shape; PrimeNG scrolls it inline.

## Classes and methods

**`FilesPage`** (`pages/files`) — the tab: reads the server from the route that declares
`:serverId` and the folder from `?path=`, shows them through the store, and closes the store when
it leaves. Puts focus on the location block when the link that opened a folder has gone with its
rows. `onRoot(path)` opens another allowed folder by URL. `onFileChosen(picker)` uploads the chosen
file into the folder on screen and empties the picker, so choosing the same file again is still a
change. `cancelUpload()` aborts and returns focus to the upload button. `newFolder()` opens the
dialog on the folder on screen. `remove(entry)` asks, then deletes. `onPaged(event)` turns the
table's page event into the store's page. `retry()` reloads the listing.

**`NewFolderDialog`** (`components/new-folder`) — asks for a folder name and creates it in the folder
it was opened on. `onName(name)` records the name and clears the backend's earlier answer.
`submit()` checks the name, creates the folder, and closes with the new `Entry`. `cancel()` closes
with nothing. Its data is `NewFolderData` (`new-folder.types.ts`).

**`FilesStore`** (`state`) — one server's files as signals, provided by the route. `show(server,
path)` lists a folder (the first allowed one for `null`) from the first page; `close()` stops
listing when the page leaves. `goToPage(page, pageSize)` and `reload()` move through the listing.
`downloadUrl(entry)` is the link a file downloads from. `uploadFile(folder, file)` sends one file
per server and follows its progress, reloading the folder if it is still on screen;
`cancelUpload()` aborts it. `resetNewFolder()` clears the last create failure;
`createFolder(folder, name)` resolves with the folder or `null` with `createError` set.
`isDeleting(entry)` marks a row busy; `remove(entry)` deletes a file or an empty folder and, when it
was the only row of a later page, steps back a page.

**`FilesApi`** (`data`) — one method per endpoint: `list`, `downloadUrl` (a URL, not a request),
`upload` (progress events, then the created entry), `createFolder`, `remove`.

**`trailOf`, `rootOf`, `folderNameProblem`** (`data/files.types.ts`) — the crumbs from a root down
to a folder; the allowed folder a path is inside; what is wrong with a folder name, the way the
backend checks it.

**`filesGuard`** (`guards`) — anyone signed in, mirroring `IsAuthenticated` on `/api/files/`.

**Types** (`data/files.types.ts`) — mirror `backend/apps/files/serializers/`; the two move together.
Every path is absolute, on the server, inside one of the server's `roots`; the backend checks that on
every request after resolving links (`path_outside_roots` otherwise).
- `EntryKind` — `file`, `folder`, `link` (a symbolic link, listed as itself and never followed) or
  `other` (socket, pipe, device). `Entry` — a listing row and the answer of an upload or new folder:
  `size` in bytes, `mode` as `ls` writes it.
- `Listing` — a page of a folder's entries, folders first then by name (`no_allowed_folders` when the
  server has none): `path` (the first allowed folder when none was asked), `parent` (`null` at an
  allowed folder), `root`, and `roots` in the order of the server's settings. `ListingQuery` —
  server, folder or `null`, one-based page, page size.
- `UploadEvent` — progress (`sent`, `total`), then the written entry. Failures are `ApiError`s:
  `file_exists`, `upload_too_large` (2 GiB default), `fields.file` codes. `NewFolder` — body of create
  (`file_exists` when taken). `Crumb` — one step from an allowed folder; the first is named by the
  allowed folder's whole path.
- `trailOf(root, folder)` — the root, then one step per folder below it; a folder outside the root is the
  root alone. `rootOf(path, roots)` — the deepest allowed folder holding `path`, or `null`.
  `FolderNameProblem` — `required`, `separator`, `reserved`; `folderNameProblem(name)` runs the
  backend's checks first: not only spaces, no `/` or `\`, neither `.` nor `..`; surrounding spaces are
  not part of the name.

**Api details** — a path travels as a query parameter or form field, never in the URL path, so
`HttpParams` and `FormData` encode it. `list` without a path lists the first allowed folder.
`downloadUrl` is a link, not a request: the session cookie goes with it same-origin and the browser
streams the file. `upload` sends `multipart/form-data`, reports bytes sent then the written entry,
and aborts on unsubscribe; the module's `uploadEventOf` maps an `HttpEvent` to an `UploadEvent` (the
file's size stands in when the browser reports no total). `remove` deletes a file or an empty folder
(`folder_not_empty` otherwise). `HttpClient` appears in this layer only.

**`filesGuard`** details — mirrors `IsAuthenticated` on every `/api/files/` view; the backend check is
the boundary (rule 21) and also keeps every path inside the allowed folders. Its own guard so
narrowing to a group is a change here and in the backend permission only.

**`files.fixtures`** (`testing`) — shapes the specs share, as the backend sends them: `SERVER_ID`;
`ROOT` and `OTHER_ROOT` (the server's two allowed folders, in settings order) and `ROOTS`; entries
`FOLDER`, `FILE`, `LINK`, `OTHER` and `NESTED` (inside `FOLDER`); `listingOf(results, options)` builds
a page of a path's entries inside its root with both roots allowed.

## Components

PrimeNG: `p-card`, the `pButton` directive, `p-select`, `p-breadcrumb`, `p-table` (with its paginator),
`p-progressbar`, `p-skeleton`, `p-tag`, `p-message`, `pInputText`. Shared: `app-field`,
`app-empty-state`, `Dialogs`, `Confirmation`, `Toaster`, `appDate`, `fileSize`.
