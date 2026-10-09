# backups

One server's backups: django-dbs backups, archives of chosen folders, and the backup files a server
already makes, collected from one folder. Plans first: add, edit, run now and delete a plan — what it
backs up (django-dbs, folders, or existing files), a schedule and how many of its backups to keep here
and (but for a collection) on the server. Then the files, newest first, tagged with what made them,
with the plan that made each one (or "One-off"), when and by whom, its size and what the last check
found: take a one-off django-dbs backup, upload a backup file from the browser, download, run a full
check, restore a django-dbs file onto its server (or rehearse it), delete with Undo. A tab of the
server page.

## Route and guard

```
/servers/:serverId/backups    BackupsPage    a tab of ServerPage (features/servers)
```

Mounted as a lazy child of `:serverId` in `features/servers/servers.routes.ts`, with a tab in the
server page's `TABS` (Overview, Backups, Files, Activity). The slice's root route carries `backupsGuard`,
`BackupsStore` and the bundles. The page itself provides `Dialogs`, so both dialogs
resolve the route's `BackupsStore`.

`backupsGuard` is "signed in" — it mirrors `IsAuthenticated` on `/api/backups/`. The backend
permission is the boundary (rule 21); narrowing backups to a group is a change to both.

## Components

PrimeNG 22 plus the shared facades: `p-card` for the two cards, `p-table` (lazy, server-side pages
through `[first]`/`[rows]`/`[totalRecords]` and `(onPage)`) for both lists, `p-tag` with a Font
Awesome icon beside its text for every state, `p-message`, `p-skeleton`, `p-progressbar` for the
upload, `<button pButton>` / `<a pButton>` for every action, and in the forms `p-radiobutton`
(inside a `fieldset`/`legend`), `p-inputtags`, `pInputText`, `p-select`, `p-inputnumber`,
`p-toggleswitch` and `<app-password-input>`, each framed by `<app-field>`. Toasts go through
`Toaster`, confirmations through `Confirmation`, dialogs through `Dialogs`; dates through `appDate`,
empty lists through `<app-empty-state>`.

A busy button is `[disabled]` with `aria-busy` and a spinning `fa-spinner` before its text, and its
text says what is happening ("Running…", "Backing up…", "Rehearsing…") — `pButton` has no loading
state of its own.

## Backend counterpart

`backend/apps/backups/`. Endpoints, all under `/api/backups/`:

| Method | Path | Store call |
|---|---|---|
| GET | `?server=&page=&page_size=` | file list resource (`open`, `goToPage`, `reload`) |
| POST | `take/` `{server}` → 202 `{activity}` | `take` — a one-off backup, then follows the job |
| POST | `upload/` multipart `server`, `file` → 201 `BackupFile` (kind `uploaded`) | `uploadFile` — the bytes sent as they go; `cancelUpload` aborts |
| GET | `{id}/download/` | `downloadUrl` — a link, not a request |
| POST | `{id}/verify/` → 202 `{activity}` | `verify` — then follows the job |
| POST | `{id}/restore/` `{mode, rehearse, account_password?, server_name?}` → 202 `{activity}` | `restore(file, request)` — then follows the job |
| DELETE | `{id}/` | `remove` (soft delete on the backend) |
| POST | `{id}/undo-delete/` | the Undo action of the toast `remove` raises |
| GET | `plans/?server=&page=&page_size=` | plan list resource (`open`, `goToPlanPage`, `reloadPlans`) |
| POST | `plans/` `{server, kind, name, interval_minutes, keep, keep_remote, enabled, paths, pattern, account_password?}` | `createPlan(kind, settings, password)` |
| PATCH | `plans/{id}/` — every setting but `server` and `kind`, `paths` and `pattern` included, and `account_password` when those two change | `updatePlan(plan, settings, password)` |
| DELETE | `plans/{id}/` — the plan's files stay listed | `removePlan` |
| POST | `plans/{id}/run/` → 202 `{activity}` | `run` — then follows the job |

And one read outside the slice's own URL: `GET /api/activity/?server=&status=running|queued`
(`unfinishedJobs`), on every `open`, to pick up jobs this page did not start. The call lives in
`BackupsApi` because a feature never imports another feature.

`GET {id}/` and `GET plans/{id}/` have no caller here: every change reloads the list.

Jobs are followed through `core/jobs` (`GET /api/activity/{id}/`). `backup.take` and `backup.run`
end `succeeded` or `failed` with an `error_code`; `backup.verify` ends `succeeded` with
`detail.validation` `verified` or `failed`. A folder plan's run is a `backup.run` too, and may end
`succeeded` with `detail.warning: 'files_changed'`. A collection's run ends `succeeded` with
`detail: {plan, collected, skipped, size}` (`CollectResult`), `collected: 0` when nothing was new.
`skipped` counts the matching files the run did not fetch: already collected, or still changing size
while copied (fetched by a later run).
`backup.restore` ends `succeeded` with `detail: {backup, mode, rehearse, records, files, flushed,
healed, copy_left?}` (`RestoreResult`), each count `null` when the server did not print it, or
`failed` with `restore_failed` or `dbs_too_old` (the server's django-dbs predates 0.2.2) among the
usual codes.
Their codes — the SSH ones, `backup_invalid`, `backup_running`, `interrupted`, the archive's
`archive_mismatch` (the checksums on the server and here differ, nothing kept) and `archive_failed`
(tar could not make it), and `remote_not_found` and `remote_permission_denied` (the folder or file is
not on the server, or cannot be reached there; the files slice shows them too) — live in `core/i18n`,
because `/activity` lists failed `backup.*` entries without this bundle loaded. So do `name_taken`,
`min_value`, `max_value` and `absolute_path_required`: the servers form shows `name_taken` and
`absolute_path_required` too, and bundles merge into one dictionary, so a code two features show
cannot have two texts. The form's own codes — `invalid_interval`, `keep_range`,
`keep_remote_range`, `paths_required`, `paths_not_allowed`, `one_folder_required`,
`invalid_pattern` — are in this bundle under `errors.*`, and so are the restore form's
`name_mismatch` and `not_restorable`. `restore_failed` and `dbs_too_old` are in `core/i18n`, since
`/activity` lists a failed restore. The upload's codes — `fields.file`'s
`empty` and `invalid_name`, and `upload_too_large` (`413`) — are in `core/i18n`: the files slice
uploads too.

A plan's `kind` is `BackupKind` (`dbs` | `archive` | `collect`); a file's is `BackupFileKind`
(`dbs` | `archive` | `collected` | `uploaded`). `backups.kind.<kind>` names all five. A plan's `paths` are absolute
folders with no `..` step: at least one for `archive`, exactly one for `collect`, `[]` for `dbs`. Its
`pattern` is the names a collection fetches (`*.sql.gz`, 1 to 200 characters, no `/`; anything else
is `invalid_pattern`), and the backend ignores it for the other kinds, which send `''`. It ignores
`keep_remote` on a collection too and always answers `0`. The form sends each kind only its own, on create and on edit: `paths: []` and
`pattern: ''` for django-dbs, the folders and `pattern: ''` for an archive, `paths: [folder]`, the
pattern and `keep_remote: 0` for a collection. Every file is stored here encrypted and downloads
plain — an archive as `.tar.gz`, a collected file under the name it had on the server.

`interval_minutes` is one of `PLAN_SCHEDULES` (`data/backups.types.ts`): `null` (manual), 60, 180,
360, 720, 1440, 10080. The page and the form name a schedule by its key there —
`backups.schedule.<key>` — never by its minutes.

## The store

One `BackupsStore`, route-provided. The route's injector is shared by every server and outlives the
page, so the page calls `open(server)` / `close()`, and every busy flag is keyed.

Writable: `server`, `page` and `planPage` (`linkedSignal`s that reset to 0 on another server),
`pageSize`, `savingPlan`, `planSaveError`, `deleting` and `deletingPlans` (`ReadonlySet` of ids),
and the private job state — `takingOn` (server ids), `runs` (`{server, plan, name}` of the plans
with a run followed, matched by plan id) and `checks` (`{server, name}` of the files with a check
followed) — and `uploads` (`{server, name, sent, total}`, one per server at most), with the
`Subscription` of each upload's request kept beside it in a plain `Map`: a handle for Cancel, not
state on screen. `restores` (`{server, name, rehearse}` of the files with a restore followed),
`sendingRestore` and `restoreError` (the form's, cleared by `resetRestoreForm`), and the private
`lastDeleted` with `undoing` beside it. Both lists load with `rxResource`; params are `undefined`
until `open`, so they load only while the page is on screen.

`createPlan(kind, settings)` takes the kind apart from `PlanSettings`, because it is fixed once the
plan exists and `updatePlan` never sends it.

`computed`: `files`, `count`, `error`, `pending`, `empty`; `plans`, `planCount`, `plansError`,
`plansPending`, `plansEmpty`; `taking` (a one-off of the server on screen), `backingUp` (a one-off
or a plan's run); `upload` (the server on screen's, or `null`), `uploading`, `uploadProgress` (0 to
100 while the file is being sent, `null` once every byte is); `deleted` (the last file deleted on
the server on screen, while Undo is still offered). `loading` and `plansLoading` are the
resources' `isLoading`. `isRunning(plan)` and `isVerifying(file)` read `runs` and `checks`; `restoring(file)` reads `restores`
and says `rehearse`, `restore` or `null`.

## Decisions

**The store raises the toasts, not the page.** Each names what it is about in its `detail` — the
file, the plan, or a restore's counts. A backup runs for minutes and the reader may leave
the tab; the store keeps following the job (until its injector is destroyed) and the toast says how
it ended wherever the reader is. Saving or deleting a plan toasts from the store as well. The page
owns only the confirmations before a delete, and opening the plan form.

**Jobs are picked up on open.** `open(server)` lists the server's `running` and `queued` activity and
follows every `backup.take`, `backup.run`, `backup.verify` and `backup.restore` it finds, so the busy state and the
outcome toast survive a reload, another tab, or a scheduled run. A job already followed is skipped
by its key, which is what stops a reopened page following its own job twice. A failed read changes
nothing on screen; the lists report their own failures.

**A run is keyed by plan id, a check by file name.** A `backup.run` entry carries
`detail.plan` from the moment it is queued, so a run picked up after a reload finds its row even
when the plan was renamed or its name reused; a run whose entry names no plan is left alone. A
`backup.verify` entry names its file only by `target`, so a check is keyed by `{server, name}` —
file names are unique per server — and a check started here is keyed the same way.

**Each list keeps its rows while the next page of the same server loads**, and never shows one
server's rows on another's tab: `shownPageOf` keeps the previous page only when the server matches.

**A sealed file's check is named for what it checks.** A django-dbs file's tag is django-dbs's own:
Structure checked, then Verified once Verify has decrypted it. Every other file is sealed here, and
Verify only opens the copy kept here, every chunk, to the digest it was kept with, so its tag says
Stored, Intact or Damaged (`sealedValidation`, chosen by `validationKey`). A text file uploaded as
`x.dbs` is Intact, which is true; "Verified" would have said it was a backup. The toasts say "Check
passed" or "Check failed" for both, since a check picked up on open knows only the file's name.

**A failed verification is a result, not an error.** It reloads the row, whose tag then reads
"Failed verification", and the toast is a danger toast naming the file. A job that could not run
the check at all is an error toast through `errorText`.

**A run's toast names the plan** in its detail, success or failure, since several plans can run on
one server. A run reloads both lists: it adds a file and may delete the plan's oldest.

**An archive whose files changed while it was made is a warning, not a failure.** The run kept the
archive, so the list reloads like any success; the toast is `warning` and reads
`backups.take.warning.<warning>`. `notifyBackedUp` serves the one-off and the run alike.

**A collection says what it fetched.** A run whose detail carries `collected` and `skipped` is a
collection, whatever the plan on screen says, so a run picked up after a reload reads the same. Its
success toast is `label: {n}` sentences — "Collected: 2. Skipped: 3.", the second only when there
were any — and a run with nothing new is a plain success, "Nothing new to collect." The
bytes in `size` are not shown.

**Restore is offered on a django-dbs file only,** in its row, and opens `RestoreForm`
(`components/restore-form`) through `Dialogs`, titled "Restore backup" by the dialog frame. The form
names the file and the server, offers Merge or Replace as two `p-radiobutton`s in a `fieldset`, and
has two ways out besides Cancel:
"Rehearse", `outlined`, which sends `rehearse: true` with nothing else, and "Restore", a `danger`
submit, which first needs "Your password" and the server's name typed out (`server_name`, the
backend's own, trimmed; `dir="auto"`, since a name may be in either script). Both checks are the
backend's too. A wrong password is said under its field and a name that does not match under its;
anything else is above the form. The form closes as soon as the job is queued: the store follows it,
the row's Restore is busy with "Rehearsing…" or "Restoring…", and the toast says what it
loaded, or would have, as `label: {n}` sentences — records, files, and for a replace the records
cleared first — a warning naming the path when the copy sent to the server could not be removed. The
counts never claim more than the server printed: a `null` count is left out. Picked up on open, a
restore keeps its `rehearse` from the entry's `detail`.

**The server's name comes on each file.** The form needs it to show what to type, and a feature
never imports another, so `servers`' store is out of reach. The backend sends `server_name` with
every `BackupFile` instead, as it is now, so a renamed server asks for its new name.

**Undo lives on the page, not in a toast.** The shared `Toaster` carries no action, so a deleted
file raises no toast: the files card shows a closable success `p-message` — "Backup deleted." and the
name — with an Undo button, until the reader closes it, deletes another file, undoes it or opens
the page again. It is keyed by server, so it never shows on another server's tab. Undo calls
`undo-delete`, reloads and toasts "Deletion undone."; a failure toasts and leaves the offer up. Once
`Toaster` can carry an action this goes back into the toast. Plans have no undo endpoint, so
deleting a plan has no Undo; its confirmation says the plan's backups stay.

**A busy button is disabled.** `pButton` has no loading state, so "Back up now", "Run now",
"Upload a backup" and the rest are `[disabled]` with `aria-busy` while their job runs; a disabled
button drops focus, which is why Cancel on an upload moves focus back to "Upload a backup" in
`afterNextRender`, once it is enabled again. The store refuses a second job on the same key as well.

**No plans is an offer, not a gap.** The empty state's action opens the form filled in for a first
plan — name `django-dbs`, daily, seven kept here, one on the server, enabled — and "Add plan" in the
card header is hidden while it shows. "Back up folders" and "Collect existing files" open the same
defaults on the Folders or Existing files kind, with no name. The first offer is the one filled
button; the other two are alternatives of equal weight, both `outlined`, a step below it, so three
actions never compete. "Add plan" opens the django-dbs defaults with no name.

**Choosing what a plan reads asks for the reader's password.** A folder archive or a collection
copies whatever the server's SSH user can read, so the form shows "Your password" at its foot while
it is adding one, or while the folders or the pattern differ from the plan's own (`needsPassword`);
the backend holds the same rule. A wrong password (`invalid_password`) is said under that field, not
above the form, and stops being said once the reader types again. If the backend asks for a password
the form did not expect (`fields.account_password`), the field shows anyway. A django-dbs plan, and a
change to a plan's name, schedule or counts, never asks.

**The kind is chosen once.** Adding a plan offers it as three `p-radiobutton`s in a `fieldset`
whose `legend` names it, the hint and any error under them; editing shows it as a label and its
value, not a disabled control. A backend error on `paths` for a django-dbs plan, which has no folder field on screen, is shown under
the kind (`kindError`). Switching the kind keeps what was typed for each kind — the archive's folder list and
the collection's folder are separate fields of the draft — and only the chosen kind's is sent.

**A collection asks for one folder and a pattern, and not for copies on the server.** It never
removes the server's files, so "Keep on the server" is hidden and `keep_remote` is sent as `0`; the
plan table's Kept cell drops "On the server" for it too. The folder is a plain `pInputText`, not
`p-inputtags`, since there is exactly one; both it and the pattern are `dir="ltr"` in
`--app-font-mono`.
The client checks are the backend's: the folder is required and absolute with no `..` step
(`required`, `absolute_path_required`), the pattern is required with no `/` (`required`,
`invalid_pattern`) and `maxlength="200"`. A new collection starts on `*`. The pattern's Arabic hint
wraps its two examples in FSI…PDI inside the bundle value, so `*.sql.gz` keeps its order inside the
Arabic sentence; the sentence is phrased so neither example ends it.

**The folder list is `p-inputtags`**, with `typeahead` off and `addOnBlur` on: Enter or leaving the
field adds the folder typed. It has no `inputId`, so the field's id and `aria-describedby` reach its
inner input through `pt` (`pcAutoComplete.pcInputText.root`). The client check is the backend's:
starts with `/`, no `..` step (`absolute_path_required`), at least one (`paths_required`). PrimeNG
draws each chip without `dir="auto"`, so in Arabic a path's slashes may sit on the wrong end of the
chip — a PrimeNG question, not a restyle here.

**Who took a file sits under when.** The file table holds six columns at desktop width. "By
{name}" is a second line of the Taken cell, and is absent when nobody signed in took it (a scheduled
run). The file's kind is a secondary tag under its name for the same reason, not a column of its own.

**What a plan backs up sits under its name.** `django-dbs` in the mono family; "Folders: {n}"
(never a count before the noun) with each folder on its own `dir="ltr"` line; or "Existing files"
with where it collects from as one `dir="ltr"` path, folder then pattern (`collectsFrom`:
`/var/backups/postgres/*.sql.gz`). These are lines a keyboard and a screen reader reach, which a
tooltip on text would not be. `p-table` scrolls sideways when its columns do not fit; it has no card
layout for narrow screens.

**An upload shows its bytes, so `HttpClient` runs on XHR.** `BackupsApi.upload` posts
`multipart/form-data` with `reportProgress: true, observe: 'events'` and maps the events to
`UploadEvent` (`progress {sent, total}`, then `uploaded {file}`), so the store never reads an
`HttpEvent`. Angular's default fetch backend reports no upload progress at all, which is why
`app.config.ts` has `withXhr()`. Unsubscribing aborts the request; that is all Cancel is.

**Uploading has two phases on screen.** While bytes go out, the files card shows the name (`dir="ltr"`
inside a line of the page's direction), "Uploading…" and a `p-progressbar` labelled by it with its
percentage, and Cancel, which returns focus to "Upload a backup" as it leaves. Once every byte is sent the backend is
storing the file, and aborting would no longer stop it: the bar goes indeterminate under "Saving the
file…" and Cancel is gone. "Upload a backup" is busy throughout. The upload is keyed by server,
carries on while another server's tab is open, and toasts from the store on success (the file name as
the backend stored it) or failure. A failure's `fields.file` code is the toast itself (`empty`,
`invalid_name`), because there is no file field on screen to show it under.

**The file picker is native.** "Upload a backup" is a secondary `pButton` that calls `click()` on a
native `<input type="file" hidden>` — out of the layout, the tab order and the accessibility tree.
`p-fileupload` brings its own list and upload flow, which the store already owns. No `accept`: a
server's backups are any file.

**The download is an `a[pButton]` with `download`.** Same-origin, so the session cookie goes with
it and the browser streams the file to disk; nothing passes through `HttpClient`.

**Sizes are decimal** (`kilobyte` = 1000 bytes), through the shared `fileSize` pipe
(`shared/file-size`), so the unit and the digits follow the application's locale.

**Paging shows only when a list is longer than its smallest page.** `p-table`'s own paginator,
`[lazy]` so the rows on screen are the page the store loaded; the files' offers 20, 50 and 100 rows,
the plans' has no size choice. Each table and paginator is labelled through `pt` (`table`,
`pcPaginator.root`), since `p-table` has no label input.

**Names render in their own direction.** File names and folders `dir="ltr"` in the mono family, plan names
`dir="auto"`, and both are wrapped in FSI…PDI inside a translated sentence (the confirmations, the
toasts, "By {name}").

## Classes and methods

**`backupsGuard`** — who may open a server's backups: anyone signed in, mirroring the backend's
`IsAuthenticated`. Its own guard so narrowing it to a group is a change here and in the backend only.

**`BackupsApi`** — transport for `/api/backups/` and the one read of `/api/activity/`: one method per
endpoint (`list`, `take`, `downloadUrl`, `verify`, `restore`, `remove`, `undoDelete`, `upload`, `plans`,
`createPlan`, `updatePlan`, `removePlan`, `runPlan`, `unfinishedJobs`), no state. `upload` reports
the bytes sent, then the stored file; unsubscribing aborts it.

**`BackupsStore`** — one server's plans and files as signals, the operations on both, and the jobs
that back up, check or restore it, followed to their end with a toast.
- `open(server)` / `close()` — start and stop showing a server's lists, from their first pages, and
  pick up its unfinished jobs.
- `goToPage(page, size)`, `reload()`, `goToPlanPage(page)`, `reloadPlans()` — move through and reload
  the two lists.
- `downloadUrl(file)` — where a file downloads from.
- `createPlan(kind, settings, password)`, `updatePlan(plan, settings, password)` — save a plan;
  resolve with it or `null` with `planSaveError` set. `resetPlanForm()` clears that error.
- `removePlan(plan)` — delete a plan; its backups stay.
- `uploadFile(file)` / `cancelUpload()` — send a file to the server on screen, or abort it.
- `take()`, `run(plan)`, `verify(file)` — start a one-off backup, a plan's run or a full check, and
  follow it. `isRunning(plan)`, `isVerifying(file)` say whether one is followed.
- `restore(file, request)` — start a restore or a rehearsal; resolves `true` once started, or `false`
  with `restoreError` set. `restoring(file)` says which is running; `resetRestoreForm()` clears the
  error.
- `remove(file)` — delete a file and offer Undo (`deleted`); `undoDelete()` brings it back;
  `dismissDeleted()` withdraws the offer.

**Types** (`data/backups.types.ts`) — mirror `backend/apps/backups/serializers/`; the two move together.
Taking a backup, running a plan, verifying and restoring are jobs: their endpoints answer
`JobStarted` (`core/jobs`) and the store follows the job to its end.
- `BackupKind` — what a plan backs up: `dbs` runs django-dbs on the server, `archive` packs the plan's
  folders into one `.tar.gz`, `collect` fetches the files of one folder matching the plan's `pattern`
  and leaves them on the server. Every file is stored here encrypted and downloads plain.
  `BackupFileKind` — what made a file: `dbs`, `archive`, `collected` or `uploaded`.
- `BackupValidation` — what the last check found. For `dbs`: `structure_ok` (django-dbs read the
  container; every backup starts here), `verified` (a full check decrypted and validated it), `failed`.
  For other kinds, sealed here: `structure_ok` kept whole, `verified` every chunk matches the digest
  it was kept with, `failed` it does not; none says whether the file inside is a usable backup.
  `VerifyOutcome` is `detail.validation` of a finished `backup.verify`; a failed check is a result.
- `BackupFile` — a row of `GET /api/backups/`. `server_name` is what a real restore asks to have
  typed; `validated_at` is `null` while only the structure was checked; `taken_by` and `plan` are
  `null` when nobody signed in took it or it was one-off; `plan_name` outlives the plan.
  `BackupListQuery`, `PlanListQuery` — server, one-based page, page size; newest first.
- `UploadEvent` — progress (`sent`, `total`), then the stored file. Failures are `ApiError`s:
  `fields.file` `required`/`empty`/`invalid_name`, `not_found`, `upload_too_large` (5 GiB default).
- `RestoreMode` — `merge` loads over existing records, `replace` clears the backed-up tables first.
  `RestoreRequest` — body of restore, `dbs` files only (`not_restorable`). A rehearsal runs in a
  rolled-back transaction and needs only the session; a real restore also needs `account_password`
  (`required`, `invalid_password`) and `server_name` typed out (`name_mismatch`).
  `RestoreResult` — `detail` of a succeeded restore: counts are `null` when the server did not print
  them, `flushed` also for a merge; `copy_left` is where the sent copy remains if it could not be removed.
- `BackupWarning` — `files_changed`: files changed while the archive was made. `CollectResult` —
  `collected` fetched this run, `skipped` matched but not fetched (already collected, or still being
  written), `size` bytes fetched; a run with nothing new succeeds with `collected: 0`.
- `PLAN_SCHEDULES` — schedule names with minutes between runs (`manual` is `null`); the backend
  accepts no other interval (`invalid_interval`). `PlanSchedule`, `PlanInterval`, and `scheduleOf(interval)`
  which names an interval (`manual` when unknown). `PlanRunStatus` — `none` until a first run.
- `BackupPlan` — a plan row. `name` is unique per server (`name_taken`); `kind` is fixed; `paths` are
  absolute folders (archive: one or more, collect: exactly one, dbs: none); `pattern` is a shell
  pattern for collect; `keep` 1 to 365 here, `keep_remote` 0 to 365 on the server (`0` removes the
  server's copy once fetched; always `0` for collect); a disabled plan runs only on demand;
  `next_run_at` is `null` when manual or disabled; `last_error_code` is a code, never prose.
- `PlanSettings` — what the form edits. `paths`: absolute, no `..` (`absolute_path_required`),
  `paths_required` / `one_folder_required` / `paths_not_allowed` by kind; `pattern`: 1 to 200 characters
  with no `/` (`invalid_pattern`), `''` for other kinds; `keep_remote` is sent `0` for collect.
  `PlanPassword` — the reader's password, required to add an `archive` or `collect` plan and to change
  its `paths` or `pattern`; a value equal to the current one is not a change. `PlanCreate`,
  `PlanUpdate` — bodies of create and PATCH.
- `UnfinishedJob` — a queued or running job of `GET /api/activity/?server=&status=`: `action`
  (`backup.take`, `backup.run`, `backup.verify`), `target` by name, and `detail`, which carries
  `{ plan }` on a `backup.run` from the moment it is queued.

**Api details** — `unfinishedJobs(server, status)` reads one status, up to 100 jobs, when the page
opens, so a backup started elsewhere or before a reload is followed too (a server's backups run one at
a time, checks start by hand). `take` and `runPlan` answer `backup_running` when one is under way.
`downloadUrl(id)` is a link, not a request: it carries the session cookie same-origin and the browser
streams the file. `remove` soft-deletes (rule 16), which lets `undoDelete` bring it back;
`removePlan` leaves the plan's backups listed; `updatePlan` cannot change server or kind. `upload`
sends `multipart/form-data`, reports bytes sent then the stored file, and aborts on unsubscribe; the
module's `uploadEventOf` maps an `HttpEvent` to an `UploadEvent` (the file's size stands in when the
browser reports no total). `HttpClient` appears in this layer only.

**`backupsGuard`** details — mirrors `IsAuthenticated` on every `/api/backups/` view; the backend
check is the boundary (rule 21). It exists apart from `authGuard` so narrowing to a group is a change
here and in the backend permission only.

**`BackupsPage`** — the tab: the plans card, then the files card with upload and one-off backup.
Asks before every delete, opens `PlanForm` and `RestoreForm`, and hands everything else to the store.
`onFileChosen(picker)` uploads what the picker returned and empties it; `cancelUpload()` aborts and
returns focus to the upload button. `validationKey(file)` names a file's check (django-dbs's own, or
the seal's); `collectsFrom(plan)` is a collection's folder and pattern as one path; `takenBy(file)`
is the "By {name}" line.

**`PlanForm`** — adds a plan to the server on screen or edits one: its kind (chosen once), folders or
folder and pattern, name, schedule, counts kept, enabled, and the reader's password when it reads the
server. `save()` checks what the backend checks, then saves through the store and closes with the
plan; `error(field)` / `errorFor(field)` give the code or the sentence under a field; `setKind`,
`setSchedule`, `update` and `setAccountPassword` edit the draft.

**`RestoreForm`** — restores a django-dbs file onto its server, or rehearses it. `rehearse()` needs
nothing more; `restore()` needs the password and the server's name typed out. Closes with `true` once
the job is started.

