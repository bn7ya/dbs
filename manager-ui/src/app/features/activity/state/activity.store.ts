import { Injectable, computed, inject, linkedSignal, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';

import { apiErrorOf } from '@core/http/api-error';
import type { Page } from '@core/http/api.types';
import { ActivityApi } from '../data/activity.api';
import type { ActivityEntry, ActivityQuery } from '../data/activity.types';
import type { ActivityStatusFilter } from './activity.store.types';

export const ACTIVITY_PAGE_SIZES: readonly number[] = [20, 50, 100];

@Injectable()
export class ActivityStore {
  private readonly api = inject(ActivityApi);

  private readonly isOpen = signal(false);

  readonly server = signal<string | null>(null);
  readonly status = signal<ActivityStatusFilter>('');
  readonly action = signal('');

  private readonly filters = computed(() => ({
    server: this.server(),
    status: this.status(),
    action: this.action(),
  }));

  readonly page = linkedSignal({ source: this.filters, computation: () => 0 });
  readonly pageSize = signal(ACTIVITY_PAGE_SIZES[0]);

  private readonly query = computed<ActivityQuery | undefined>(() => {
    if (!this.isOpen()) {
      return undefined;
    }
    const { server, status, action } = this.filters();
    return {
      server: server ?? undefined,
      status: status || undefined,
      action: action || undefined,
      page: this.page() + 1,
      page_size: this.pageSize(),
    };
  });

  private readonly listResource = rxResource({
    params: () => this.query(),
    stream: ({ params }) => this.api.list(params),
  });

  // Keeps the last page up while the next one loads, so the table never blinks to a skeleton.
  private readonly shownPage = linkedSignal<
    { readonly open: boolean; readonly page: Page<ActivityEntry> | undefined },
    Page<ActivityEntry> | undefined
  >({
    source: () => ({
      open: this.query() !== undefined,
      page: this.listResource.hasValue() ? this.listResource.value() : undefined,
    }),
    computation: ({ open, page }, previous) => page ?? (open ? previous?.value : undefined),
  });

  readonly entries = computed<ActivityEntry[]>(() => [...(this.shownPage()?.results ?? [])]);
  readonly count = computed(() => this.shownPage()?.count ?? 0);
  readonly loading = this.listResource.isLoading;
  readonly error = computed(() => apiErrorOf(this.listResource.error()));
  readonly pending = computed(() => this.shownPage() === undefined && this.loading());
  readonly empty = computed(() => this.shownPage()?.count === 0);
  readonly filtered = computed(() => this.status() !== '' || this.action() !== '');

  open(server: string | null): void {
    this.server.set(server);
    this.status.set('');
    this.action.set('');
    this.page.set(0);
    this.isOpen.set(true);
  }

  close(): void {
    this.isOpen.set(false);
  }

  setStatus(status: ActivityStatusFilter): void {
    this.status.set(status);
  }

  setAction(action: string): void {
    this.action.set(action);
  }

  clearFilters(): void {
    this.status.set('');
    this.action.set('');
  }

  goToPage(page: number, pageSize: number): void {
    this.pageSize.set(pageSize);
    this.page.set(page);
  }

  reload(): void {
    this.listResource.reload();
  }
}
