import { DestroyRef, Injectable, computed, inject, linkedSignal, signal, type ResourceRef, type Signal } from '@angular/core';
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
  type Observable,
  type Subscription,
} from 'rxjs';

import { apiErrorOf } from '@core/http/api-error';
import type { ApiError, Page } from '@core/http/api.types';
import { errorText } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { JobWatcher } from '@core/jobs/job-watcher';
import type { Job, JobStarted } from '@core/jobs/job.types';
import { Toaster } from '@shared/toaster/toaster';
import type { ToastSeverity } from '@shared/toaster/toaster.types';
import { BackupsApi } from '../data/backups.api';
import type {
  BackupFile,
  BackupKind,
  BackupListQuery,
  BackupPlan,
  BackupWarning,
  PlanListQuery,
  PlanPassword,
  PlanSettings,
  RestoreRequest,
  RestoreResult,
  TargetServer,
  UnfinishedJob,
  UploadEvent,
  VerifyOutcome,
} from '../data/backups.types';
import type { CollectCounts, JobTarget, PlanRun, RestoreProgress, RestoreTarget, Upload } from './backups.store.types';

export const BACKUP_PAGE_SIZES: readonly number[] = [20, 50, 100];

export const PLAN_PAGE_SIZE = 20;

@Injectable()
export class BackupsStore {
  private readonly api = inject(BackupsApi);
  private readonly jobs = inject(JobWatcher);
  private readonly toaster = inject(Toaster);
  private readonly locale = inject(LocaleStore);
  private readonly destroyRef = inject(DestroyRef);

  private readonly isOpen = signal(false);

  readonly server = signal<string | null>(null);

  private readonly listed = computed(() => (this.isOpen() ? this.server() : null));

  open(server: string): void {
    this.server.set(server);
    this.page.set(0);
    this.planPage.set(0);
    this.lastDeleted.set(null);
    this.isOpen.set(true);
    this.pickUpJobs(server);
  }

  close(): void {
    this.isOpen.set(false);
  }

  readonly page = linkedSignal({ source: this.server, computation: () => 0 });
  readonly pageSize = signal(BACKUP_PAGE_SIZES[0]);

  private readonly query = computed<BackupListQuery | undefined>(() => {
    const server = this.listed();
    return server === null ? undefined : { server, page: this.page() + 1, page_size: this.pageSize() };
  });

  private readonly listResource = rxResource({
    params: () => this.query(),
    stream: ({ params }) => this.api.list(params),
  });

  private readonly shownPage = shownPageOf(() => this.query()?.server ?? null, this.listResource);

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

  downloadUrl(file: BackupFile): string {
    return this.api.downloadUrl(file.id);
  }

  readonly planPage = linkedSignal({ source: this.server, computation: () => 0 });

  private readonly planQuery = computed<PlanListQuery | undefined>(() => {
    const server = this.listed();
    return server === null ? undefined : { server, page: this.planPage() + 1, page_size: PLAN_PAGE_SIZE };
  });

  private readonly plansResource = rxResource({
    params: () => this.planQuery(),
    stream: ({ params }) => this.api.plans(params),
  });

  private readonly shownPlans = shownPageOf(() => this.planQuery()?.server ?? null, this.plansResource);

  readonly plans = computed<readonly BackupPlan[]>(() => this.shownPlans()?.results ?? []);
  readonly planCount = computed(() => this.shownPlans()?.count ?? 0);
  readonly plansLoading = this.plansResource.isLoading;
  readonly plansError = computed(() => apiErrorOf(this.plansResource.error()));

  readonly plansPending = computed(() => this.shownPlans() === undefined && this.plansLoading());

  readonly plansEmpty = computed(() => this.shownPlans()?.count === 0);

  goToPlanPage(page: number): void {
    this.planPage.set(page);
  }

  reloadPlans(): void {
    this.plansResource.reload();
  }

  readonly savingPlan = signal(false);
  readonly planSaveError = signal<ApiError | null>(null);

  resetPlanForm(): void {
    this.planSaveError.set(null);
  }

  async createPlan(kind: BackupKind, settings: PlanSettings, password: PlanPassword = {}): Promise<BackupPlan | null> {
    const server = this.server();
    if (server === null) {
      return null;
    }
    return this.savePlan(this.api.createPlan({ ...settings, ...password, server, kind }), 'backups.plans.created');
  }

  async updatePlan(plan: BackupPlan, settings: PlanSettings, password: PlanPassword = {}): Promise<BackupPlan | null> {
    return this.savePlan(this.api.updatePlan(plan.id, { ...settings, ...password }), 'backups.plans.saved');
  }

  private async savePlan(saving: Observable<BackupPlan>, doneKey: string): Promise<BackupPlan | null> {
    this.savingPlan.set(true);
    this.planSaveError.set(null);
    let saved: BackupPlan;
    try {
      saved = await firstValueFrom(saving);
    } catch (error) {
      this.planSaveError.set(error as ApiError);
      return null;
    } finally {
      this.savingPlan.set(false);
    }
    this.plansResource.reload();
    this.notify('success', this.locale.translate(doneKey), isolated(saved.name));
    return saved;
  }

  readonly deletingPlans = signal<ReadonlySet<string>>(new Set());

  async removePlan(plan: BackupPlan): Promise<boolean> {
    this.deletingPlans.update((ids) => withItem(ids, plan.id));
    try {
      await firstValueFrom(this.api.removePlan(plan.id));
    } catch (error) {
      this.notifyFailure(error as ApiError);
      return false;
    } finally {
      this.deletingPlans.update((ids) => withoutItem(ids, plan.id));
    }
    this.plansResource.reload();
    this.notify('success', this.locale.translate('backups.plans.delete.done'), isolated(plan.name));
    return true;
  }

  private readonly uploads = signal<readonly Upload[]>([]);

  // A handle for Cancel, not state on screen.
  private readonly uploadRequests = new Map<string, Subscription>();

  readonly upload = computed(() => {
    const server = this.server();
    return this.uploads().find((upload) => upload.server === server) ?? null;
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
    const server = this.server();
    if (server === null || this.uploads().some((upload) => upload.server === server)) {
      return;
    }
    this.uploads.update((uploads) => [...uploads, { server, name: file.name, sent: 0, total: file.size }]);
    const request = this.api
      .upload(server, file)
      .pipe(
        finalize(() => {
          this.uploadRequests.delete(server);
          this.uploads.update((uploads) => uploads.filter((upload) => upload.server !== server));
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (event) => this.onUploadEvent(server, event),
        error: (error: ApiError) => this.notifyFailure(uploadErrorOf(error), file.name),
      });
    if (!request.closed) {
      this.uploadRequests.set(server, request);
    }
  }

  cancelUpload(): void {
    const server = this.server();
    if (server !== null) {
      this.uploadRequests.get(server)?.unsubscribe();
    }
  }

  private onUploadEvent(server: string, event: UploadEvent): void {
    if (event.kind === 'progress') {
      this.uploads.update((uploads) =>
        uploads.map((upload) => (upload.server === server ? { ...upload, sent: event.sent, total: event.total } : upload)),
      );
      return;
    }
    this.listResource.reload();
    this.notify('success', this.locale.translate('backups.upload.done'), isolated(event.file.name));
  }

  private readonly takingOn = signal<ReadonlySet<string>>(new Set());

  private readonly runs = signal<readonly PlanRun[]>([]);

  private readonly checks = signal<readonly JobTarget[]>([]);

  readonly taking = computed(() => {
    const server = this.server();
    return server !== null && this.takingOn().has(server);
  });

  readonly backingUp = computed(() => {
    const server = this.server();
    return this.taking() || this.runs().some((run) => run.server === server);
  });

  isRunning(plan: BackupPlan): boolean {
    return this.runs().some((run) => run.plan === plan.id);
  }

  isVerifying(file: BackupFile): boolean {
    return includes(this.checks(), file);
  }

  take(): void {
    const server = this.server();
    if (server !== null) {
      this.followTake(server, this.api.take(server));
    }
  }

  run(plan: BackupPlan): void {
    this.followRun({ server: plan.server, plan: plan.id, name: plan.name }, this.api.runPlan(plan.id));
  }

  verify(file: BackupFile): void {
    this.followCheck(targetOf(file), this.api.verify(file.id));
  }

  private pickUpJobs(server: string): void {
    forkJoin([this.api.unfinishedJobs(server, 'running'), this.api.unfinishedJobs(server, 'queued')])
      .pipe(
        map((pages) => pages.flatMap((page) => page.results)),
        catchError(() => of<UnfinishedJob[]>([])),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((jobs) => {
        for (const job of jobs) {
          this.pickUp(server, job);
        }
      });
  }

  private pickUp(server: string, job: UnfinishedJob): void {
    const started = of<JobStarted>({ activity: job.id });
    const plan = job.detail['plan'];
    switch (job.action) {
      case 'backup.take':
        this.followTake(server, started);
        return;
      case 'backup.run':
        if (typeof plan === 'string') {
          this.followRun({ server, plan, name: job.target }, started);
        }
        return;
      case 'backup.verify':
        this.followCheck({ server, name: job.target }, started);
        return;
      case 'backup.restore':
        this.followRestore({ server, name: job.target, rehearse: job.detail['rehearse'] !== false }, started);
        return;
    }
  }

  private followTake(server: string, started: Observable<JobStarted>): void {
    if (this.takingOn().has(server)) {
      return;
    }
    this.takingOn.update((servers) => withItem(servers, server));
    this.follow(started, () => this.takingOn.update((servers) => withoutItem(servers, server))).subscribe({
      next: (job) => {
        this.listResource.reload();
        if (job.status === 'succeeded') {
          this.notifyBackedUp(job);
        } else {
          this.notifyFailure(job.error_code);
        }
      },
      error: (error: ApiError) => this.notifyFailure(error),
    });
  }

  private followRun(plan: PlanRun, started: Observable<JobStarted>): void {
    if (this.runs().some((run) => run.plan === plan.plan)) {
      return;
    }
    this.runs.update((runs) => [...runs, plan]);
    this.follow(started, () => this.runs.update((runs) => runs.filter((run) => run.plan !== plan.plan))).subscribe({
      next: (job) => {
        this.plansResource.reload();
        this.listResource.reload();
        if (job.status === 'succeeded') {
          this.notifyBackedUp(job, plan.name);
        } else {
          this.notifyFailure(job.error_code, plan.name);
        }
      },
      error: (error: ApiError) => this.notifyFailure(error, plan.name),
    });
  }

  private followCheck(file: JobTarget, started: Observable<JobStarted>): void {
    if (includes(this.checks(), file)) {
      return;
    }
    this.checks.update((checks) => [...checks, file]);
    this.follow(started, () => this.checks.update((checks) => checks.filter((check) => !sameTarget(check, file))))
      .subscribe({
        next: (job) => {
          this.listResource.reload();
          if (job.status === 'failed') {
            this.notifyFailure(job.error_code);
            return;
          }
          const outcome = outcomeOf(job);
          if (outcome === null) {
            this.notifyFailure('unexpected');
            return;
          }
          this.notify(
            outcome === 'verified' ? 'success' : 'danger',
            this.locale.translate(`backups.verify.${outcome}`),
            isolated(file.name),
          );
        },
        error: (error: ApiError) => this.notifyFailure(error),
      });
  }

  private follow(started: Observable<JobStarted>, done: () => void): Observable<Job> {
    return started.pipe(
      switchMap(({ activity }) => this.jobs.watch(activity)),
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

  private readonly targetsWanted = signal(false);

  private readonly targetsResource = rxResource({
    params: () => (this.targetsWanted() ? (this.server() ?? undefined) : undefined),
    stream: () => this.api.targetServers(),
  });

  readonly targetServers = computed<readonly TargetServer[]>(() => {
    const page = this.targetsResource.hasValue() ? this.targetsResource.value() : undefined;
    return (page?.results ?? []).filter((each) => each.id !== this.server());
  });

  resetRestoreForm(): void {
    this.restoreError.set(null);
    this.targetsWanted.set(true);
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
    this.follow(started, () =>
      this.restores.update((restores) => restores.filter((restore) => !sameTarget(restore, file))),
    ).subscribe({
      next: (job) => {
        const result = job.status === 'succeeded' ? restoreResultOf(job) : null;
        if (result === null) {
          this.notifyFailure(job.error_code || 'unexpected', file.name);
        } else {
          this.notifyRestored(result);
        }
      },
      error: (error: ApiError) => this.notifyFailure(error, file.name),
    });
  }

  private notifyRestored(result: RestoreResult): void {
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
    this.notify(
      result.copy_left ? 'warning' : 'success',
      this.locale.translate(result.rehearse ? 'backups.restore.rehearsed' : 'backups.restore.done'),
      lines.length === 0 ? undefined : lines.join(' '),
    );
  }

  readonly deleting = signal<ReadonlySet<string>>(new Set());

  // The Undo offer lives on the page until the shared toast can carry an action.
  private readonly lastDeleted = signal<BackupFile | null>(null);

  readonly deleted = computed(() => {
    const file = this.lastDeleted();
    return file !== null && file.server === this.server() ? file : null;
  });

  readonly undoing = signal(false);

  async remove(file: BackupFile): Promise<boolean> {
    this.deleting.update((ids) => withItem(ids, file.id));
    try {
      await firstValueFrom(this.api.remove(file.id));
    } catch (error) {
      this.notifyFailure(error as ApiError);
      return false;
    } finally {
      this.deleting.update((ids) => withoutItem(ids, file.id));
    }
    this.listResource.reload();
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
      this.notifyFailure(error as ApiError);
      return;
    } finally {
      this.undoing.set(false);
    }
    this.lastDeleted.set(null);
    this.listResource.reload();
    this.notify('success', this.locale.translate('backups.delete.undone'));
  }

  dismissDeleted(): void {
    this.lastDeleted.set(null);
  }

  private notifyBackedUp(job: Job, name?: string): void {
    const warning = warningOf(job);
    const collected = collectResultOf(job);
    let summary: string;
    if (collected !== null) {
      summary = this.collectedText(collected);
    } else if (warning !== null) {
      summary = this.locale.translate(`backups.take.warning.${warning}`);
    } else {
      summary = this.locale.translate('backups.take.done');
    }
    this.notify(warning === null ? 'success' : 'warning', summary, name === undefined ? undefined : isolated(name));
  }

  private collectedText({ collected, skipped }: CollectCounts): string {
    if (collected === 0) {
      return this.locale.translate('backups.collect.nothingNew');
    }
    const lines = [this.locale.translate('backups.collect.collected', { count: collected })];
    if (skipped > 0) {
      lines.push(this.locale.translate('backups.collect.skipped', { count: skipped }));
    }
    return lines.join(' ');
  }

  private notifyFailure(error: ApiError | string, name?: string): void {
    this.notify('danger', errorText(this.locale, error), name === undefined ? undefined : isolated(name));
  }

  private notify(severity: ToastSeverity, summary: string, detail?: string): void {
    this.toaster.add(detail === undefined ? { severity, summary } : { severity, summary, detail });
  }
}

function shownPageOf<T>(
  server: () => string | null,
  resource: ResourceRef<Page<T> | undefined>,
): Signal<Page<T> | undefined> {
  return linkedSignal<
    { readonly server: string | null; readonly page: Page<T> | undefined },
    Page<T> | undefined
  >({
    source: () => ({ server: server(), page: resource.hasValue() ? resource.value() : undefined }),
    computation: ({ server, page }, previous) =>
      page ?? (server !== null && server === previous?.source.server ? previous.value : undefined),
  });
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

function warningOf(job: Job): BackupWarning | null {
  return job.detail['warning'] === 'files_changed' ? 'files_changed' : null;
}

function collectResultOf(job: Job): CollectCounts | null {
  const { collected, skipped } = job.detail;
  return typeof collected === 'number' && typeof skipped === 'number' ? { collected, skipped } : null;
}

// No file field is on screen, so the file's own code (`empty`, `invalid_name`) is the message.
function uploadErrorOf(error: ApiError): ApiError | string {
  return error.fields?.['file']?.[0] ?? error;
}

// FSI … PDI: a name keeps its own direction inside a line of either language.
function isolated(text: string): string {
  return `⁨${text}⁩`;
}

function targetOf({ server, name }: JobTarget): JobTarget {
  return { server, name };
}

function sameTarget(a: JobTarget, b: JobTarget): boolean {
  return a.server === b.server && a.name === b.name;
}

function includes(targets: readonly JobTarget[], target: JobTarget): boolean {
  return targets.some((each) => sameTarget(each, target));
}

function withItem(items: ReadonlySet<string>, item: string): ReadonlySet<string> {
  return new Set(items).add(item);
}

function withoutItem(items: ReadonlySet<string>, item: string): ReadonlySet<string> {
  const rest = new Set(items);
  rest.delete(item);
  return rest;
}
