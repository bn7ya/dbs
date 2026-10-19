import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { MatButton, MatIconButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { MatMenu, MatMenuItem, MatMenuTrigger } from '@angular/material/menu';
import { MatPaginator, type PageEvent } from '@angular/material/paginator';
import { MatTableModule } from '@angular/material/table';

import { Can } from '@core/auth/directives/can';
import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { routeParam } from '@core/routing/route-param';
import { AppDatePipe } from '@shared/app-date/app-date.pipe';
import { Confirmation } from '@shared/confirm/confirmation';
import { Dialogs } from '@shared/dialogs/dialogs';
import { EmptyState } from '@shared/empty-state/empty-state';
import { isolated } from '@shared/isolated/isolated';
import { JobConnection } from '@shared/job-connection/job-connection';
import { Notice } from '@shared/notice/notice';
import { Skeleton } from '@shared/skeleton/skeleton';
import { StatusTag } from '@shared/status-tag/status-tag';
import { NextRun } from '../../components/next-run/next-run';
import { PlanForm } from '../../components/plan-form/plan-form';
import type { PlanFormData } from '../../components/plan-form/plan-form.types';
import { RescheduleForm } from '../../components/reschedule-form/reschedule-form';
import type { RescheduleFormData } from '../../components/reschedule-form/reschedule-form.types';
import { scheduleOf, type BackupPlan, type PlanRunStatus } from '../../data/plans.types';
import { PLAN_PAGE_SIZE, PlansStore } from '../../state/plans.store';
import type { TagLook } from '../../components/backup-table/backup-table.types';

const RUN_LOOKS: Readonly<Record<Exclude<PlanRunStatus, 'none'>, TagLook>> = {
  succeeded: { severity: 'success', icon: 'fa-solid fa-circle-check' },
  failed: { severity: 'danger', icon: 'fa-solid fa-circle-exclamation' },
};

const FIRST_PLAN_NAME = 'django-dbs';

@Component({
  selector: 'app-plans-page',
  imports: [
    Can,
    MatButton,
    MatIconButton,
    MatCard,
    MatCardContent,
    MatMenu,
    MatMenuItem,
    MatMenuTrigger,
    MatPaginator,
    MatTableModule,
    JobConnection,
    NextRun,
    Notice,
    Skeleton,
    StatusTag,
    AppDatePipe,
    EmptyState,
    ErrorTextPipe,
    TranslatePipe,
  ],
  providers: [Dialogs],
  templateUrl: './plans.html',
  styleUrl: './plans.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PlansPage {
  private readonly store = inject(PlansStore);
  private readonly dialogs = inject(Dialogs);
  private readonly confirmation = inject(Confirmation);
  private readonly locale = inject(LocaleStore);

  readonly applicationId = routeParam(inject(ActivatedRoute), 'applicationId');

  readonly rows = computed(() => [...this.store.plans()]);
  readonly count = this.store.count;
  readonly page = this.store.page;
  readonly pageSize = PLAN_PAGE_SIZE;
  readonly loading = this.store.loading;
  readonly pending = this.store.pending;
  readonly error = this.store.error;
  readonly empty = this.store.empty;
  readonly running = this.store.running;
  readonly liveConnection = this.store.liveConnection;

  readonly columns = ['plan', 'schedule', 'kept', 'nextRun', 'lastRun', 'actions'];
  readonly skeleton = [0, 1, 2];

  readonly paginated = computed(() => this.count() > PLAN_PAGE_SIZE);

  constructor() {
    effect(() => {
      const application = this.applicationId();
      if (application !== null) {
        this.store.open(application);
      }
    });
    inject(DestroyRef).onDestroy(() => this.store.close());
  }

  scheduleKey(plan: BackupPlan): string {
    return `backups.schedule.${scheduleOf(plan.interval_minutes)}`;
  }

  scheduled(plan: BackupPlan): boolean {
    return plan.interval_minutes !== null;
  }

  nextRun(plan: BackupPlan): string | null {
    return plan.enabled && plan.interval_minutes !== null ? plan.next_run_at : null;
  }

  runLook(status: Exclude<PlanRunStatus, 'none'>): TagLook {
    return RUN_LOOKS[status];
  }

  collectsFrom(plan: BackupPlan): string {
    const folder = plan.paths[0] ?? '';
    return folder.endsWith('/') ? `${folder}${plan.pattern}` : `${folder}/${plan.pattern}`;
  }

  isRunning(plan: BackupPlan): boolean {
    return this.store.isRunning(plan);
  }

  isBusy(plan: BackupPlan): boolean {
    return this.store.isChanging(plan) || this.store.deleting().has(plan.id);
  }

  addPlan(): void {
    this.openPlanForm({ plan: null });
  }

  addFirstPlan(): void {
    this.openPlanForm({ plan: null, name: FIRST_PLAN_NAME });
  }

  addFolderPlan(): void {
    this.openPlanForm({ plan: null, kind: 'archive' });
  }

  addCollectPlan(): void {
    this.openPlanForm({ plan: null, kind: 'collect' });
  }

  editPlan(plan: BackupPlan): void {
    this.openPlanForm({ plan });
  }

  run(plan: BackupPlan): void {
    this.store.run(plan);
  }

  pause(plan: BackupPlan): void {
    void this.store.pause(plan);
  }

  resume(plan: BackupPlan): void {
    void this.store.resume(plan);
  }

  reschedule(plan: BackupPlan): void {
    this.dialogs.open<BackupPlan, RescheduleFormData>(RescheduleForm, {
      titleKey: 'backups.plans.reschedule.title',
      data: { plan },
      size: 'sm',
    });
  }

  async removePlan(plan: BackupPlan): Promise<void> {
    const accepted = await this.confirmation.ask({
      title: this.locale.translate('backups.plans.delete.confirmTitle', { name: isolated(plan.name) }),
      message: this.locale.translate('backups.plans.delete.confirmBody'),
      acceptLabel: this.locale.translate('actions.delete'),
      rejectLabel: this.locale.translate('actions.cancel'),
      acceptSeverity: 'danger',
    });
    if (accepted) {
      await this.store.removePlan(plan);
    }
  }

  onPaged(event: PageEvent): void {
    this.store.goToPage(event.pageIndex);
  }

  retry(): void {
    this.store.reload();
  }

  private openPlanForm(data: PlanFormData): void {
    const titleKey = data.plan ? 'backups.plans.form.editTitle' : 'backups.plans.form.addTitle';
    this.dialogs.open<BackupPlan, PlanFormData>(PlanForm, { titleKey, data, size: 'md' });
  }
}
