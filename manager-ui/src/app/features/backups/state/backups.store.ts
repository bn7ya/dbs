import { DestroyRef, Injectable, computed, inject, linkedSignal, signal } from '@angular/core';
import { rxResource, takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  catchError,
  finalize,
  firstValueFrom,
  forkJoin,
  last,
  map,
  of,
  switchMap,
  tap,
  type Observable,
  type Subscription,
} from 'rxjs';

import { apiErrorOf } from '@core/http/api-error';
import type { ApiError } from '@core/http/api.types';
import { LocaleStore } from '@core/i18n/locale.store';
import { JobWatcher } from '@core/jobs/job-watcher';
import type { Job, JobConnection, JobStarted } from '@core/jobs/job.types';
import { isolated } from '@shared/isolated/isolated';
import { Toaster } from '@shared/toaster/toaster';
import type { ToastMessage } from '@shared/toaster/toaster.types';
import { BackupsApi } from '../data/backups.api';
import type {
  ApplicationChoice,
  BackupFile,
  BackupListQuery,
  Dashboard,
  RestoreRequest,
  RestoreResult,
  UnfinishedJob,
  UploadEvent,
  VerifyOutcome,
} from '../data/backups.types';
import { backedUpToast, failureToast, toast } from './backup-toasts';
import type {
  BackupScope,
  JobTarget,
  LiveJob,
  RestoreProgress,
  RestoreTarget,
  Storage,
  Upload,
} from './backups.store.types';
import { shownPageOf, withItem, withoutItem, withoutKey } from './store-helpers';

export const BACKUP_PAGE_SIZES: readonly number[] = [20, 50, 100];

@Injectable()
export class BackupsStore {
  private readonly api = inject(BackupsApi);
  private readonly jobs = inject(JobWatcher);
  private readonly toaster = inject(Toaster);
  private readonly locale = inject(LocaleStore);
  private readonly destroyRef = inject(DestroyRef);

  private readonly scope = signal<BackupScope | null>(null);

  readonly application = computed(() => this.scope()?.application ?? null);

  private readonly everyApplication = computed(() => this.scope()?.every === true);

  private readonly listKey = computed(() => {
    const scope = this.scope();
    return scope === null ? null : `${scope.every ? 'every' : 'one'}:${scope.application ?? ''}`;
  });

  openApplication(application: string): void {
    this.begin({ every: false, application });
    this.pickUpJobs(application);
  }

  openEvery(): void {
    this.begin({ every: true, application: null });
    this.applicationsWanted.set(true);
    this.pickUpJobs(null);
  }

  filterBy(application: string | null): void {
    this.scope.update((scope) => (scope?.every ? { every: true, application } : scope));
  }

  close(): void {
    this.scope.set(null);
  }

  private begin(scope: BackupScope): void {
    this.scope.set(scope);
    this.page.set(0);
    this.lastDeleted.set(null);
  }

  private inScope(application: string): boolean {
    const scope = this.scope();
    if (scope === null) {
      return false;
    }
    return scope.application === null ? scope.every : scope.application === application;
  }

  readonly page = linkedSignal({ source: this.listKey, computation: () => 0 });
  readonly pageSize = signal(BACKUP_PAGE_SIZES[0]);

  private readonly query = computed<BackupListQuery | undefined>(() => {
    const scope = this.scope();
    return scope === null
      ? undefined
      : { application: scope.application, page: this.page() + 1, page_size: this.pageSize() };
  });

  private readonly listResource = rxResource({
    params: () => this.query(),
    stream: ({ params }) => this.api.list(params),
  });

  private readonly shownPage = shownPageOf(this.listKey, this.listResource);

  readonly files = computed<readonly BackupFile[]>(() => this.shownPage()?.results ?? []);
  readonly count = computed(() => this.shownPage()?.count ?? 0);
  readonly loading = this.listResource.isLoading;
  readonly error = computed(() => apiErrorOf(this.listResource.error()));

  readonly pending = computed(() => this.shownPage() === undefined && this.loading());

  readonly empty = computed(() => this.shownPage()?.count === 0);

  goToPage(page: number, pageSize: number): void {
    this.pageSize.set(pageSize);
    this.page.set(page);
  }

  reload(): void {
    this.listResource.reload();
  }

  private readonly storageResource = rxResource({
    params: () => (this.everyApplication() ? true : undefined),
    stream: () => this.api.storage(),
  });

  readonly storage = computed<Storage | null>(() => {
    const resource = this.storageResource;
    return resource.hasValue() ? storageOf(resource.value()) : null;
  });

  readonly storageError = computed(() => apiErrorOf(this.storageResource.error()));

  reloadStorage(): void {
    this.storageResource.reload();
  }

  // The list and, on the page of every backup, the storage it adds up to.
  private changed(): void {
    this.listResource.reload();
    if (this.everyApplication()) {
      this.storageResource.reload();
    }
  }

  private readonly applicationsWanted = signal(false);

  private readonly applicationsResource = rxResource({
    params: () => (this.applicationsWanted() ? true : undefined),
    stream: () => this.api.applications(),
  });

  readonly applications = computed<readonly ApplicationChoice[]>(() => {
    const resource = this.applicationsResource;
    return resource.hasValue() ? resource.value().results : [];
  });

  downloadUrl(file: BackupFile): string {
    return this.api.downloadUrl(file.id);
  }

  readonly downloadError = signal<ApiError | null>(null);

  async downloadLink(file: BackupFile, password: string): Promise<string | null> {
    this.downloadError.set(null);
    try {
      const { url } = await firstValueFrom(this.api.downloadLink(file.id, password));
      return url;
    } catch (error) {
      this.downloadError.set(error as ApiError);
      return null;
    }
  }

  private readonly uploads = signal<readonly Upload[]>([]);

  // A handle for Cancel, not state on screen.
  private readonly uploadRequests = new Map<string, Subscription>();

  readonly upload = computed(() => {
    const application = this.application();
    return this.uploads().find((upload) => upload.application === application) ?? null;
  });

  readonly uploading = computed(() => this.upload() !== null);

  readonly uploadProgress = computed(() => {
    const upload = this.upload();
    if (upload === null || upload.sent >= upload.total) {
      return null;
    }
    return Math.floor((upload.sent / upload.total) * 100);
  });

  uploadFile(file: File): void {
    const application = this.application();
    if (application === null || this.uploads().some((upload) => upload.application === application)) {
      return;
    }
    this.uploads.update((uploads) => [...uploads, { application, name: file.name, sent: 0, total: file.size }]);
    const request = this.api
      .upload(application, file)
      .pipe(
        finalize(() => {
          this.uploadRequests.delete(application);
          this.uploads.update((uploads) => uploads.filter((upload) => upload.application !== application));
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (event) => this.onUploadEvent(application, event),
        error: (error: ApiError) => this.notify(failureToast(this.locale, uploadErrorOf(error), file.name)),
      });
    if (!request.closed) {
      this.uploadRequests.set(application, request);
    }
  }

  cancelUpload(): void {
    const application = this.application();
    if (application !== null) {
      this.uploadRequests.get(application)?.unsubscribe();
    }
  }

  private onUploadEvent(application: string, event: UploadEvent): void {
    if (event.kind === 'progress') {
      this.uploads.update((uploads) =>
        uploads.map((upload) =>
          upload.application === application ? { ...upload, sent: event.sent, total: event.total } : upload,
        ),
      );
      return;
    }
    this.changed();
    this.notify(toast('success', this.locale.translate('backups.upload.done'), event.file.name));
  }

  private readonly takingOn = signal<ReadonlySet<string>>(new Set());

  private readonly runs = signal<readonly JobTarget[]>([]);

  private readonly checks = signal<readonly JobTarget[]>([]);

  readonly taking = computed(() => {
    const scope = this.scope();
    return scope !== null && !scope.every && scope.application !== null && this.takingOn().has(scope.application);
  });

  readonly backingUp = computed(
    () =>
      [...this.takingOn()].some((application) => this.inScope(application)) ||
      this.runs().some((run) => this.inScope(run.application)),
  );

  private readonly liveJobs = signal<ReadonlyMap<number, LiveJob>>(new Map());

  readonly liveConnection = computed<JobConnection | null>(() => {
    const live = [...this.liveJobs().values()].find((each) => this.inScope(each.application) && each.job.connection);
    return live?.job.connection ?? null;
  });

  isVerifying(file: BackupFile): boolean {
    return includes(this.checks(), file);
  }

  take(): void {
    const application = this.application();
    if (application !== null && !this.everyApplication()) {
      this.followTake(application, this.api.take(application));
    }
  }

  verify(file: BackupFile): void {
    this.followCheck(targetOf(file), this.api.verify(file.id));
  }

  private pickUpJobs(application: string | null): void {
    forkJoin([this.api.unfinishedJobs(application, 'running'), this.api.unfinishedJobs(application, 'queued')])
      .pipe(
        map((pages) => pages.flatMap((page) => page.results)),
        catchError(() => of<UnfinishedJob[]>([])),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((jobs) => {
        for (const job of jobs) {
          this.pickUp(application, job);
        }
      });
  }

  private pickUp(scoped: string | null, job: UnfinishedJob): void {
    const application = job.application ?? scoped;
    if (application === null) {
      return;
    }
    const started = of<JobStarted>({ activity: job.id });
    const target = { application, name: job.target };
    switch (job.action) {
      case 'backup.take':
        this.followTake(application, started);
        return;
      case 'backup.run':
        this.followRun(target, started);
        return;
      case 'backup.verify':
        this.followCheck(target, started);
        return;
      case 'backup.restore': {
        // A restore onto another application is listed under that one; its file belongs to the source.
        const source = job.detail['source_application'];
        const file = typeof source === 'string' ? { ...target, application: source } : target;
        this.followRestore({ ...file, rehearse: job.detail['rehearse'] !== false }, started);
        return;
      }
    }
  }

  private followTake(application: string, started: Observable<JobStarted>): void {
    if (this.takingOn().has(application)) {
      return;
    }
    this.takingOn.update((applications) => withItem(applications, application));
    this.follow(application, started, () =>
      this.takingOn.update((applications) => withoutItem(applications, application)),
    ).subscribe({
      next: (job) => {
        this.changed();
        this.notify(
          job.status === 'succeeded' ? backedUpToast(this.locale, job) : failureToast(this.locale, job.error_code),
        );
      },
      error: (error: ApiError) => this.notify(failureToast(this.locale, error)),
    });
  }

  private followRun(run: JobTarget, started: Observable<JobStarted>): void {
    if (includes(this.runs(), run)) {
      return;
    }
    this.runs.update((runs) => [...runs, run]);
    this.follow(run.application, started, () =>
      this.runs.update((runs) => runs.filter((each) => !sameTarget(each, run))),
    ).subscribe({
      next: (job) => {
        this.changed();
        this.notify(
          job.status === 'succeeded'
            ? backedUpToast(this.locale, job, run.name)
            : failureToast(this.locale, job.error_code, run.name),
        );
      },
      error: (error: ApiError) => this.notify(failureToast(this.locale, error, run.name)),
    });
  }

  private followCheck(file: JobTarget, started: Observable<JobStarted>): void {
    if (includes(this.checks(), file)) {
      return;
    }
    this.checks.update((checks) => [...checks, file]);
    this.follow(file.application, started, () =>
      this.checks.update((checks) => checks.filter((check) => !sameTarget(check, file))),
    ).subscribe({
      next: (job) => {
        this.listResource.reload();
        if (job.status === 'failed') {
          this.notify(failureToast(this.locale, job.error_code));
          return;
        }
        const outcome = outcomeOf(job);
        if (outcome === null) {
          this.notify(failureToast(this.locale, 'unexpected'));
          return;
        }
        const severity = outcome === 'verified' ? 'success' : 'danger';
        this.notify(toast(severity, this.locale.translate(`backups.verify.${outcome}`), file.name));
      },
      error: (error: ApiError) => this.notify(failureToast(this.locale, error)),
    });
  }

  private follow(application: string, started: Observable<JobStarted>, done: () => void): Observable<Job> {
    return started.pipe(
      switchMap(({ activity }) =>
        this.jobs.watch(activity).pipe(
          tap((job) => this.liveJobs.update((jobs) => new Map(jobs).set(activity, { application, job }))),
          finalize(() => this.liveJobs.update((jobs) => withoutKey(jobs, activity))),
        ),
      ),
      last(),
      finalize(done),
      takeUntilDestroyed(this.destroyRef),
    );
  }

  private readonly restores = signal<readonly RestoreTarget[]>([]);

  readonly sendingRestore = signal(false);
  readonly restoreError = signal<ApiError | null>(null);

  restoring(file: BackupFile): RestoreProgress | null {
    const restore = this.restores().find((each) => sameTarget(each, file));
    if (restore === undefined) {
      return null;
    }
    return restore.rehearse ? 'rehearse' : 'restore';
  }

  resetRestoreForm(): void {
    this.restoreError.set(null);
    this.applicationsWanted.set(true);
  }

  async restore(file: BackupFile, request: RestoreRequest): Promise<boolean> {
    this.sendingRestore.set(true);
    this.restoreError.set(null);
    let started: JobStarted;
    try {
      started = await firstValueFrom(this.api.restore(file.id, request));
    } catch (error) {
      this.restoreError.set(error as ApiError);
      return false;
    } finally {
      this.sendingRestore.set(false);
    }
    this.followRestore({ ...targetOf(file), rehearse: request.rehearse }, of(started));
    return true;
  }

  private followRestore(file: RestoreTarget, started: Observable<JobStarted>): void {
    if (includes(this.restores(), file)) {
      return;
    }
    this.restores.update((restores) => [...restores, file]);
    this.follow(file.application, started, () =>
      this.restores.update((restores) => restores.filter((restore) => !sameTarget(restore, file))),
    ).subscribe({
      next: (job) => {
        const result = job.status === 'succeeded' ? restoreResultOf(job) : null;
        this.notify(
          result === null
            ? failureToast(this.locale, job.error_code || 'unexpected', file.name)
            : this.restoredToast(result),
        );
      },
      error: (error: ApiError) => this.notify(failureToast(this.locale, error, file.name)),
    });
  }

  private restoredToast(result: RestoreResult): ToastMessage {
    const counted = (key: string, count: number | null) =>
      count === null ? [] : [this.locale.translate(`backups.restore.${key}`, { count })];
    const lines = [
      ...counted('records', result.records),
      ...counted('files', result.files),
      ...counted(result.rehearse ? 'toClear' : 'cleared', result.flushed),
    ];
    if (result.healed) {
      lines.push(this.locale.translate('backups.restore.healed'));
    }
    if (result.copy_left) {
      lines.push(this.locale.translate('backups.restore.copyLeft', { path: isolated(result.copy_left) }));
    }
    const summary = this.locale.translate(result.rehearse ? 'backups.restore.rehearsed' : 'backups.restore.done');
    const severity = result.copy_left ? 'warning' : 'success';
    return lines.length === 0 ? { severity, summary } : { severity, summary, detail: lines.join(' ') };
  }

  readonly deleting = signal<ReadonlySet<string>>(new Set());

  // The Undo offer lives on the page until the shared toast can carry an action.
  private readonly lastDeleted = signal<BackupFile | null>(null);

  readonly deleted = computed(() => {
    const file = this.lastDeleted();
    return file !== null && this.inScope(file.application) ? file : null;
  });

  readonly undoing = signal(false);

  readonly deleteError = signal<ApiError | null>(null);

  async remove(file: BackupFile, password: string): Promise<boolean> {
    this.deleting.update((ids) => withItem(ids, file.id));
    this.deleteError.set(null);
    try {
      await firstValueFrom(this.api.remove(file.id, password));
    } catch (error) {
      this.deleteError.set(error as ApiError);
      return false;
    } finally {
      this.deleting.update((ids) => withoutItem(ids, file.id));
    }
    this.changed();
    this.lastDeleted.set(file);
    return true;
  }

  async undoDelete(): Promise<void> {
    const file = this.deleted();
    if (file === null || this.undoing()) {
      return;
    }
    this.undoing.set(true);
    try {
      await firstValueFrom(this.api.undoDelete(file.id));
    } catch (error) {
      this.notify(failureToast(this.locale, error as ApiError));
      return;
    } finally {
      this.undoing.set(false);
    }
    this.lastDeleted.set(null);
    this.changed();
    this.notify(toast('success', this.locale.translate('backups.delete.undone')));
  }

  dismissDeleted(): void {
    this.lastDeleted.set(null);
  }

  private notify(message: ToastMessage): void {
    this.toaster.add(message);
  }
}

function storageOf(dashboard: Dashboard): Storage {
  const applications = dashboard.servers.flatMap((server) =>
    server.applications.map((application) => ({
      id: application.id,
      name: application.name,
      server: server.id,
      serverName: server.name,
      bytes: application.storage_bytes,
    })),
  );
  return {
    total: dashboard.storage_bytes,
    applications: applications.sort((a, b) => b.bytes - a.bytes || a.name.localeCompare(b.name)),
  };
}

function outcomeOf(job: Job): VerifyOutcome | null {
  const validation = job.detail['validation'];
  return validation === 'verified' || validation === 'failed' ? validation : null;
}

function restoreResultOf(job: Job): RestoreResult | null {
  const { rehearse, records, files, flushed, healed, copy_left } = job.detail;
  if (typeof rehearse !== 'boolean') {
    return null;
  }
  return {
    rehearse,
    records: countOf(records),
    files: countOf(files),
    flushed: countOf(flushed),
    healed: healed === true,
    ...(typeof copy_left === 'string' && copy_left !== '' ? { copy_left } : {}),
  };
}

function countOf(value: unknown): number | null {
  return typeof value === 'number' ? value : null;
}

// No file field is on screen, so the file's own code (`empty`, `invalid_name`) is the message.
function uploadErrorOf(error: ApiError): ApiError | string {
  return error.fields?.['file']?.[0] ?? error;
}

function targetOf({ application, name }: JobTarget): JobTarget {
  return { application, name };
}

function sameTarget(a: JobTarget, b: JobTarget): boolean {
  return a.application === b.application && a.name === b.name;
}

function includes(targets: readonly JobTarget[], target: JobTarget): boolean {
  return targets.some((each) => sameTarget(each, target));
}
