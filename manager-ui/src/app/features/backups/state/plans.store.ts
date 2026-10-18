import { DestroyRef, Injectable, computed, inject, linkedSignal, signal } from '@angular/core';
import { rxResource, takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { catchError, finalize, firstValueFrom, forkJoin, last, map, of, switchMap, tap, type Observable } from 'rxjs';

import { apiErrorOf } from '@core/http/api-error';
import type { ApiError } from '@core/http/api.types';
import { LocaleStore } from '@core/i18n/locale.store';
import { JobWatcher } from '@core/jobs/job-watcher';
import type { JobConnection, JobStarted } from '@core/jobs/job.types';
import { Toaster } from '@shared/toaster/toaster';
import type { ToastMessage } from '@shared/toaster/toaster.types';
import type { UnfinishedJob } from '../data/backups.types';
import { PlansApi } from '../data/plans.api';
import type { BackupPlan, PlanKind, PlanListQuery, PlanPassword, PlanSettings } from '../data/plans.types';
import { backedUpToast, failureToast, refusalToast, toast } from './backup-toasts';
import type { LiveJob } from './backups.store.types';
import type { PlanChange, PlanRun } from './plans.store.types';
import { shownPageOf, withItem, withoutItem, withoutKey } from './store-helpers';

export const PLAN_PAGE_SIZE = 20;

@Injectable()
export class PlansStore {
  private readonly api = inject(PlansApi);
  private readonly jobs = inject(JobWatcher);
  private readonly toaster = inject(Toaster);
  private readonly locale = inject(LocaleStore);
  private readonly destroyRef = inject(DestroyRef);

  private readonly isOpen = signal(false);

  readonly application = signal<string | null>(null);

  private readonly listed = computed(() => (this.isOpen() ? this.application() : null));

  open(application: string): void {
    this.application.set(application);
    this.page.set(0);
    this.isOpen.set(true);
    this.pickUpRuns(application);
  }

  close(): void {
    this.isOpen.set(false);
  }

  readonly page = linkedSignal({ source: this.application, computation: () => 0 });

  private readonly query = computed<PlanListQuery | undefined>(() => {
    const application = this.listed();
    return application === null ? undefined : { application, page: this.page() + 1, page_size: PLAN_PAGE_SIZE };
  });

  private readonly listResource = rxResource({
    params: () => this.query(),
    stream: ({ params }) => this.api.list(params),
  });

  private readonly shownPage = shownPageOf(this.listed, this.listResource);

  readonly plans = computed<readonly BackupPlan[]>(() => this.shownPage()?.results ?? []);
  readonly count = computed(() => this.shownPage()?.count ?? 0);
  readonly loading = this.listResource.isLoading;
  readonly error = computed(() => apiErrorOf(this.listResource.error()));

  readonly pending = computed(() => this.shownPage() === undefined && this.loading());

  readonly empty = computed(() => this.shownPage()?.count === 0);

  goToPage(page: number): void {
    this.page.set(page);
  }

  reload(): void {
    this.listResource.reload();
  }

  readonly saving = signal(false);
  readonly saveError = signal<ApiError | null>(null);

  resetPlanForm(): void {
    this.saveError.set(null);
  }

  async createPlan(kind: PlanKind, settings: PlanSettings, password: PlanPassword = {}): Promise<BackupPlan | null> {
    const application = this.application();
    if (application === null) {
      return null;
    }
    return this.save(this.api.create({ ...settings, ...password, application, kind }), 'backups.plans.created');
  }

  async updatePlan(plan: BackupPlan, settings: PlanSettings, password: PlanPassword = {}): Promise<BackupPlan | null> {
    return this.save(this.api.update(plan.id, { ...settings, ...password }), 'backups.plans.saved');
  }

  private async save(saving: Observable<BackupPlan>, doneKey: string): Promise<BackupPlan | null> {
    this.saving.set(true);
    this.saveError.set(null);
    let saved: BackupPlan;
    try {
      saved = await firstValueFrom(saving);
    } catch (error) {
      this.saveError.set(error as ApiError);
      return null;
    } finally {
      this.saving.set(false);
    }
    this.listResource.reload();
    this.notify(toast('success', this.locale.translate(doneKey), saved.name));
    return saved;
  }

  readonly deleting = signal<ReadonlySet<string>>(new Set());

  async removePlan(plan: BackupPlan): Promise<boolean> {
    this.deleting.update((ids) => withItem(ids, plan.id));
    try {
      await firstValueFrom(this.api.remove(plan.id));
    } catch (error) {
      this.notify(failureToast(this.locale, error as ApiError));
      return false;
    } finally {
      this.deleting.update((ids) => withoutItem(ids, plan.id));
    }
    this.listResource.reload();
    this.notify(toast('success', this.locale.translate('backups.plans.delete.done'), plan.name));
    return true;
  }

  private readonly changing = signal<ReadonlySet<string>>(new Set());

  isChanging(plan: BackupPlan): boolean {
    return this.changing().has(plan.id);
  }

  pause(plan: BackupPlan): Promise<boolean> {
    return this.change(plan, 'pause');
  }

  resume(plan: BackupPlan): Promise<boolean> {
    return this.change(plan, 'resume');
  }

  private async change(plan: BackupPlan, change: PlanChange): Promise<boolean> {
    if (this.isChanging(plan)) {
      return false;
    }
    this.changing.update((ids) => withItem(ids, plan.id));
    try {
      await firstValueFrom(change === 'pause' ? this.api.pause(plan.id) : this.api.resume(plan.id));
    } catch (error) {
      this.notify(refusalToast(this.locale, error as ApiError, plan.name));
      return false;
    } finally {
      this.changing.update((ids) => withoutItem(ids, plan.id));
    }
    this.listResource.reload();
    this.notify(toast('success', this.locale.translate(`backups.plans.${change}.done`), plan.name));
    return true;
  }

  readonly rescheduling = signal(false);
  readonly rescheduleError = signal<ApiError | null>(null);

  resetRescheduleForm(): void {
    this.rescheduleError.set(null);
  }

  async reschedule(plan: BackupPlan, nextRunAt: string): Promise<BackupPlan | null> {
    this.rescheduling.set(true);
    this.rescheduleError.set(null);
    let saved: BackupPlan;
    try {
      saved = await firstValueFrom(this.api.reschedule(plan.id, { next_run_at: nextRunAt }));
    } catch (error) {
      this.rescheduleError.set(error as ApiError);
      return null;
    } finally {
      this.rescheduling.set(false);
    }
    this.listResource.reload();
    this.notify(toast('success', this.locale.translate('backups.plans.reschedule.done'), plan.name));
    return saved;
  }

  private readonly runs = signal<readonly PlanRun[]>([]);

  private readonly liveRuns = signal<ReadonlyMap<number, LiveJob>>(new Map());

  readonly running = computed(() => {
    const application = this.listed();
    return this.runs().some((run) => run.application === application);
  });

  readonly liveConnection = computed<JobConnection | null>(() => {
    const application = this.listed();
    const live = [...this.liveRuns().values()].find((each) => each.application === application && each.job.connection);
    return live?.job.connection ?? null;
  });

  isRunning(plan: BackupPlan): boolean {
    return this.runs().some((run) => run.plan === plan.id);
  }

  run(plan: BackupPlan): void {
    this.followRun({ application: plan.application, plan: plan.id, name: plan.name }, this.api.run(plan.id));
  }

  private pickUpRuns(application: string): void {
    forkJoin([this.api.unfinishedRuns(application, 'running'), this.api.unfinishedRuns(application, 'queued')])
      .pipe(
        map((pages) => pages.flatMap((page) => page.results)),
        catchError(() => of<UnfinishedJob[]>([])),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((jobs) => {
        for (const job of jobs) {
          const plan = job.detail['plan'];
          if (job.action === 'backup.run' && typeof plan === 'string') {
            this.followRun({ application, plan, name: job.target }, of<JobStarted>({ activity: job.id }));
          }
        }
      });
  }

  private followRun(run: PlanRun, started: Observable<JobStarted>): void {
    if (this.runs().some((each) => each.plan === run.plan)) {
      return;
    }
    this.runs.update((runs) => [...runs, run]);
    started
      .pipe(
        switchMap(({ activity }) =>
          this.jobs.watch(activity).pipe(
            tap((job) =>
              this.liveRuns.update((runs) => new Map(runs).set(activity, { application: run.application, job })),
            ),
            finalize(() => this.liveRuns.update((runs) => withoutKey(runs, activity))),
          ),
        ),
        last(),
        finalize(() => this.runs.update((runs) => runs.filter((each) => each.plan !== run.plan))),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (job) => {
          this.listResource.reload();
          this.notify(
            job.status === 'succeeded'
              ? backedUpToast(this.locale, job, run.name)
              : failureToast(this.locale, job.error_code, run.name),
          );
        },
        error: (error: ApiError) => this.notify(failureToast(this.locale, error, run.name)),
      });
  }

  private notify(message: ToastMessage): void {
    this.toaster.add(message);
  }
}
