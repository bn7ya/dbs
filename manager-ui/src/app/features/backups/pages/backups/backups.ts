import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  effect,
  inject,
  signal,
  viewChild,
  type Signal,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';
import { MatButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { MatPaginator, type PageEvent } from '@angular/material/paginator';
import { MatProgressBar } from '@angular/material/progress-bar';
import { MatTableModule } from '@angular/material/table';
import { map } from 'rxjs';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { AppDatePipe } from '@shared/app-date/app-date.pipe';
import { Confirmation } from '@shared/confirm/confirmation';
import { Dialogs } from '@shared/dialogs/dialogs';
import { EmptyState } from '@shared/empty-state/empty-state';
import { FileSizePipe } from '@shared/file-size/file-size.pipe';
import { Notice } from '@shared/notice/notice';
import { Skeleton } from '@shared/skeleton/skeleton';
import { StatusTag } from '@shared/status-tag/status-tag';
import { uniqueId } from '@shared/unique-id';
import { PlanForm } from '../../components/plan-form/plan-form';
import type { PlanFormData } from '../../components/plan-form/plan-form.types';
import { RestoreForm } from '../../components/restore-form/restore-form';
import type { RestoreFormData } from '../../components/restore-form/restore-form.types';
import {
  scheduleOf,
  type BackupFile,
  type BackupPlan,
  type BackupValidation,
  type PlanRunStatus,
} from '../../data/backups.types';
import { BACKUP_PAGE_SIZES, BackupsStore, PLAN_PAGE_SIZE } from '../../state/backups.store';
import type { RestoreProgress } from '../../state/backups.store.types';
import type { TagLook } from './backups.types';

const VALIDATION_LOOKS: Readonly<Record<BackupValidation, TagLook>> = {
  structure_ok: { severity: 'neutral', icon: 'fa-solid fa-check' },
  verified: { severity: 'success', icon: 'fa-solid fa-shield-check' },
  failed: { severity: 'danger', icon: 'fa-solid fa-circle-exclamation' },
};

const RUN_LOOKS: Readonly<Record<Exclude<PlanRunStatus, 'none'>, TagLook>> = {
  succeeded: { severity: 'success', icon: 'fa-solid fa-circle-check' },
  failed: { severity: 'danger', icon: 'fa-solid fa-circle-exclamation' },
};

const FIRST_PLAN_NAME = 'django-dbs';

@Component({
  selector: 'app-backups-page',
  imports: [
    MatButton,
    MatCard,
    MatCardContent,
    MatPaginator,
    MatProgressBar,
    MatTableModule,
    Notice,
    Skeleton,
    StatusTag,
    AppDatePipe,
    EmptyState,
    ErrorTextPipe,
    FileSizePipe,
    TranslatePipe,
  ],
  providers: [Dialogs],
  templateUrl: './backups.html',
  styleUrl: './backups.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BackupsPage {
  private readonly store = inject(BackupsStore);
  private readonly dialogs = inject(Dialogs);
  private readonly confirmation = inject(Confirmation);
  private readonly locale = inject(LocaleStore);
  private readonly injector = inject(Injector);

  readonly serverId = serverIdOf(inject(ActivatedRoute));

  readonly planRows = computed(() => [...this.store.plans()]);
  readonly planCount = this.store.planCount;
  readonly planPage = this.store.planPage;
  readonly planPageSize = PLAN_PAGE_SIZE;
  readonly plansLoading = this.store.plansLoading;
  readonly plansPending = this.store.plansPending;
  readonly plansError = this.store.plansError;
  readonly plansEmpty = this.store.plansEmpty;

  readonly fileRows = computed(() => [...this.store.files()]);
  readonly count = this.store.count;
  readonly pageSize = this.store.pageSize;
  readonly page = this.store.page;
  readonly pageSizes = [...BACKUP_PAGE_SIZES];
  readonly loading = this.store.loading;
  readonly pending = this.store.pending;
  readonly error = this.store.error;
  readonly empty = this.store.empty;
  readonly taking = this.store.taking;
  readonly backingUp = this.store.backingUp;
  readonly upload = this.store.upload;
  readonly uploading = this.store.uploading;
  readonly uploadProgress = this.store.uploadProgress;
  readonly deleted = this.store.deleted;
  readonly undoing = this.store.undoing;

  readonly uploadLabelId = uniqueId('backups-upload');
  readonly planSkeleton = [0, 1, 2];
  readonly fileSkeleton = [0, 1, 2, 3, 4, 5];

  private readonly uploadButton = viewChild.required<unknown, ElementRef<HTMLButtonElement>>('uploadButton', {
    read: ElementRef,
  });

  readonly plansPaginated = computed(() => this.planCount() > PLAN_PAGE_SIZE);

  readonly paginated = computed(() => this.count() > BACKUP_PAGE_SIZES[0]);

  constructor() {
    effect(() => {
      const server = this.serverId();
      if (server !== null) {
        this.store.open(server);
      }
    });
    inject(DestroyRef).onDestroy(() => this.store.close());
  }

  scheduleKey(plan: BackupPlan): string {
    return `backups.schedule.${scheduleOf(plan.interval_minutes)}`;
  }

  nextRun(plan: BackupPlan): string | null {
    return plan.enabled && plan.interval_minutes !== null ? plan.next_run_at : null;
  }

  runLook(status: Exclude<PlanRunStatus, 'none'>): TagLook {
    return RUN_LOOKS[status];
  }

  isRunning(plan: BackupPlan): boolean {
    return this.store.isRunning(plan);
  }

  isDeletingPlan(plan: BackupPlan): boolean {
    return this.store.deletingPlans().has(plan.id);
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

  collectsFrom(plan: BackupPlan): string {
    const folder = plan.paths[0] ?? '';
    return folder.endsWith('/') ? `${folder}${plan.pattern}` : `${folder}/${plan.pattern}`;
  }

  editPlan(plan: BackupPlan): void {
    this.openPlanForm({ plan });
  }

  run(plan: BackupPlan): void {
    this.store.run(plan);
  }

  async removePlan(plan: BackupPlan): Promise<void> {
    const accepted = await this.confirmation.ask({
      title: this.locale.translate('backups.plans.delete.confirmTitle', { name: `⁨${plan.name}⁩` }),
      message: this.locale.translate('backups.plans.delete.confirmBody'),
      acceptLabel: this.locale.translate('actions.delete'),
      rejectLabel: this.locale.translate('actions.cancel'),
      acceptSeverity: 'danger',
    });
    if (accepted) {
      await this.store.removePlan(plan);
    }
  }

  onPlansPaged(event: PageEvent): void {
    this.store.goToPlanPage(event.pageIndex);
  }

  retryPlans(): void {
    this.store.reloadPlans();
  }

  private openPlanForm(data: PlanFormData): void {
    const titleKey = data.plan ? 'backups.plans.form.editTitle' : 'backups.plans.form.addTitle';
    this.dialogs.open<BackupPlan, PlanFormData>(PlanForm, { titleKey, data, size: 'md' });
  }

  look(validation: BackupValidation): TagLook {
    return VALIDATION_LOOKS[validation];
  }

  validationKey(file: BackupFile): string {
    return `backups.${file.kind === 'dbs' ? 'validation' : 'sealedValidation'}.${file.validation}`;
  }

  takenBy(file: BackupFile): string | null {
    return file.taken_by === null ? null : this.locale.translate('backups.list.by', { name: `⁨${file.taken_by}⁩` });
  }

  downloadUrl(file: BackupFile): string {
    return this.store.downloadUrl(file);
  }

  isVerifying(file: BackupFile): boolean {
    return this.store.isVerifying(file);
  }

  isDeleting(file: BackupFile): boolean {
    return this.store.deleting().has(file.id);
  }

  take(): void {
    this.store.take();
  }

  verify(file: BackupFile): void {
    this.store.verify(file);
  }

  restoring(file: BackupFile): RestoreProgress | null {
    return this.store.restoring(file);
  }

  restoreKey(file: BackupFile): string {
    switch (this.store.restoring(file)) {
      case 'rehearse':
        return 'backups.restore.rehearsing';
      case 'restore':
        return 'backups.restore.working';
      default:
        return 'backups.restore.action';
    }
  }

  canRestore(file: BackupFile): boolean {
    return file.kind === 'dbs';
  }

  restore(file: BackupFile): void {
    this.dialogs.open<boolean, RestoreFormData>(RestoreForm, {
      titleKey: 'backups.restore.title',
      data: { file },
      size: 'md',
    });
  }

  // Emptied first, so choosing the same file again is still a change.
  onFileChosen(picker: HTMLInputElement): void {
    const file = picker.files?.item(0) ?? null;
    picker.value = '';
    if (file !== null) {
      this.store.uploadFile(file);
    }
  }

  // Cancel leaves with the upload; focus goes back once the button that started it is enabled again.
  cancelUpload(): void {
    this.store.cancelUpload();
    afterNextRender(() => this.uploadButton().nativeElement.focus(), {
      injector: this.injector,
    });
  }

  async remove(file: BackupFile): Promise<void> {
    const accepted = await this.confirmation.ask({
      title: this.locale.translate('backups.delete.confirmTitle', { name: `⁨${file.name}⁩` }),
      message: this.locale.translate('backups.delete.confirmBody'),
      acceptLabel: this.locale.translate('actions.delete'),
      rejectLabel: this.locale.translate('actions.cancel'),
      acceptSeverity: 'danger',
    });
    if (accepted) {
      await this.store.remove(file);
    }
  }

  undoDelete(): void {
    void this.store.undoDelete();
  }

  dismissDeleted(): void {
    this.store.dismissDeleted();
  }

  onPaged(event: PageEvent): void {
    this.store.goToPage(event.pageIndex, event.pageSize);
  }

  retry(): void {
    this.store.reload();
  }
}

// Router param inheritance stops at the server page, so the param is read from the route declaring it.
function serverIdOf(route: ActivatedRoute): Signal<string | null> {
  const owner = route.pathFromRoot.find((step) => step.snapshot.paramMap.has('serverId'));
  if (!owner) {
    return signal(null).asReadonly();
  }
  return toSignal(owner.paramMap.pipe(map((params) => params.get('serverId'))), { requireSync: true });
}
