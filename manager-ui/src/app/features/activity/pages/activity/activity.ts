import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { MatButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { MatOption } from '@angular/material/core';
import { MatFormField, MatLabel } from '@angular/material/form-field';
import { MatPaginator, type PageEvent } from '@angular/material/paginator';
import { MatSelect } from '@angular/material/select';
import { MatTableModule } from '@angular/material/table';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { routeParam } from '@core/routing/route-param';
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
import type { ActivityScope, ActivityStatusFilter } from '../../state/activity.store.types';
import type { FilterOption, StatusLook } from './activity.types';

const STATUS_LOOKS: Readonly<Record<ActivityStatus, StatusLook>> = {
  queued: { severity: 'neutral', icon: 'fa-solid fa-clock' },
  running: { severity: 'info', icon: 'fa-solid fa-spinner' },
  succeeded: { severity: 'success', icon: 'fa-solid fa-circle-check' },
  failed: { severity: 'danger', icon: 'fa-solid fa-circle-xmark' },
};

const COLUMNS: Readonly<Record<ActivityScope['kind'], readonly string[]>> = {
  all: ['when', 'action', 'status', 'application', 'server', 'target', 'by', 'ip'],
  server: ['when', 'action', 'status', 'application', 'target', 'by', 'ip'],
  application: ['when', 'action', 'status', 'target', 'by', 'ip'],
};

const EMPTY_BODIES: Readonly<Record<ActivityScope['kind'], string>> = {
  all: 'activity.empty.body',
  server: 'activity.empty.serverBody',
  application: 'activity.empty.applicationBody',
};

const ACCOUNT_ACTION_PREFIXES: readonly string[] = ['account.', 'auth.', 'manager.'];

const KEPT_ON_SERVER = 'kept_on_server';

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
  private readonly route = inject(ActivatedRoute);

  private readonly serverId = routeParam(this.route, 'serverId');
  private readonly applicationId = routeParam(this.route, 'applicationId');

  readonly scope = computed<ActivityScope>(() => {
    const application = this.applicationId();
    if (application !== null) {
      return { kind: 'application', id: application };
    }
    const server = this.serverId();
    return server === null ? { kind: 'all' } : { kind: 'server', id: server };
  });
  readonly scoped = computed(() => this.scope().kind !== 'all');

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

  readonly columns = computed(() => [...COLUMNS[this.scope().kind]]);

  readonly emptyBody = computed(() => EMPTY_BODIES[this.scope().kind]);

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
    effect(() => this.store.open(this.scope()));
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

  keptOnServer(entry: ActivityEntry): boolean {
    return entry.status === 'succeeded' && entry.detail['outcome'] === KEPT_ON_SERVER;
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
