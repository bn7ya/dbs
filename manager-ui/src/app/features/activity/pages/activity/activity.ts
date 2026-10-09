import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
  type Signal,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { MatButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { MatOption } from '@angular/material/core';
import { MatFormField, MatLabel } from '@angular/material/form-field';
import { MatPaginator, type PageEvent } from '@angular/material/paginator';
import { MatSelect } from '@angular/material/select';
import { MatTableModule } from '@angular/material/table';
import { map } from 'rxjs';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { AppDatePipe } from '@shared/app-date/app-date.pipe';
import { EmptyState } from '@shared/empty-state/empty-state';
import { Notice } from '@shared/notice/notice';
import { Skeleton } from '@shared/skeleton/skeleton';
import { StatusTag } from '@shared/status-tag/status-tag';
import {
  ACTIVITY_ACTIONS,
  ACTIVITY_STATUSES,
  type ActivityEntry,
  type ActivityStatus,
} from '../../data/activity.types';
import { ACTIVITY_PAGE_SIZES, ActivityStore } from '../../state/activity.store';
import type { ActivityStatusFilter } from '../../state/activity.store.types';
import type { FilterOption, StatusLook } from './activity.types';

const STATUS_LOOKS: Readonly<Record<ActivityStatus, StatusLook>> = {
  queued: { severity: 'neutral', icon: 'fa-solid fa-clock' },
  running: { severity: 'info', icon: 'fa-solid fa-spinner' },
  succeeded: { severity: 'success', icon: 'fa-solid fa-circle-check' },
  failed: { severity: 'danger', icon: 'fa-solid fa-circle-xmark' },
};

const ACCOUNT_ACTION_PREFIXES: readonly string[] = ['account.', 'auth.', 'manager.'];

const isAccountAction = (code: string): boolean => ACCOUNT_ACTION_PREFIXES.some((prefix) => code.startsWith(prefix));

@Component({
  selector: 'app-activity-page',
  imports: [
    FormsModule,
    RouterLink,
    MatButton,
    MatCard,
    MatCardContent,
    MatFormField,
    MatLabel,
    MatSelect,
    MatOption,
    MatPaginator,
    MatTableModule,
    Notice,
    Skeleton,
    StatusTag,
    AppDatePipe,
    EmptyState,
    ErrorTextPipe,
    TranslatePipe,
  ],
  templateUrl: './activity.html',
  styleUrl: './activity.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ActivityPage {
  private readonly store = inject(ActivityStore);
  private readonly locale = inject(LocaleStore);

  readonly serverId = serverIdOf(inject(ActivatedRoute));
  readonly scoped = computed(() => this.serverId() !== null);

  readonly entries = this.store.entries;
  readonly count = this.store.count;
  readonly status = this.store.status;
  readonly action = this.store.action;
  readonly pageSize = this.store.pageSize;
  readonly page = this.store.page;
  readonly pageSizes = [...ACTIVITY_PAGE_SIZES];
  readonly loading = this.store.loading;
  readonly pending = this.store.pending;
  readonly error = this.store.error;
  readonly empty = this.store.empty;
  readonly filtered = this.store.filtered;
  readonly skeletonLines = [1, 2, 3, 4, 5, 6];

  readonly columns = computed(() =>
    this.scoped()
      ? ['when', 'action', 'status', 'target', 'by', 'ip']
      : ['when', 'action', 'status', 'server', 'target', 'by', 'ip'],
  );

  readonly statusOptions = computed<FilterOption<ActivityStatusFilter>[]>(() => [
    { value: '', label: this.locale.translate('activity.filters.allStatuses') },
    ...ACTIVITY_STATUSES.map((status) => ({
      value: status,
      label: this.locale.translate(`activity.status.${status}`),
    })),
  ]);

  readonly actionOptions = computed<FilterOption<string>[]>(() => {
    const offered = this.scoped()
      ? ACTIVITY_ACTIONS.filter((code) => !isAccountAction(code))
      : ACTIVITY_ACTIONS;
    return [
      { value: '', label: this.locale.translate('activity.filters.allActions') },
      ...offered.map((code) => ({ value: code, label: this.actionLabel(code) })),
    ];
  });

  constructor() {
    effect(() => this.store.open(this.serverId()));
    inject(DestroyRef).onDestroy(() => this.store.close());
  }

  actionLabel(code: string): string {
    const key = `activity.actions.${code}`;
    return this.locale.has(key) ? this.locale.translate(key) : code;
  }

  look(status: ActivityStatus): StatusLook {
    return STATUS_LOOKS[status];
  }

  scheduled(entry: ActivityEntry): boolean {
    return !isAccountAction(entry.action);
  }

  onStatus(value: ActivityStatusFilter | null): void {
    this.store.setStatus(value ?? '');
  }

  onAction(value: string | null): void {
    this.store.setAction(value ?? '');
  }

  clearFilters(): void {
    this.store.clearFilters();
  }

  onPaged(event: PageEvent): void {
    this.store.goToPage(event.pageIndex, event.pageSize);
  }

  retry(): void {
    this.store.reload();
  }
}

// The router's param inheritance stops at the server page, so `:serverId` is read from the route that declares it.
function serverIdOf(route: ActivatedRoute): Signal<string | null> {
  const owner = route.pathFromRoot.find((step) => step.snapshot.paramMap.has('serverId'));
  if (!owner) {
    return signal(null).asReadonly();
  }
  return toSignal(owner.paramMap.pipe(map((params) => params.get('serverId'))), { requireSync: true });
}
