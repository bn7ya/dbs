import { Injectable, computed, inject } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';

import { apiErrorOf } from '@core/http/api-error';
import { DashboardApi } from '../data/dashboard.api';
import type { Dashboard, DashboardFailure, DashboardServer } from '../data/dashboard.types';

export const EXPORT_STALE_DAYS = 7;

const DAY_MS = 24 * 60 * 60 * 1000;

@Injectable()
export class DashboardStore {
  private readonly api = inject(DashboardApi);

  private readonly resource = rxResource({ stream: () => this.api.get() });

  private readonly dashboard = computed<Dashboard | undefined>(() =>
    this.resource.hasValue() ? this.resource.value() : undefined,
  );

  readonly loading = this.resource.isLoading;
  readonly error = computed(() => apiErrorOf(this.resource.error()));
  readonly pending = computed(() => this.dashboard() === undefined && this.loading());

  readonly servers = computed<readonly DashboardServer[]>(() => this.dashboard()?.servers ?? []);
  readonly failures = computed<DashboardFailure[]>(() => [...(this.dashboard()?.recent_failures ?? [])]);
  readonly empty = computed(() => this.dashboard() !== undefined && this.servers().length === 0);

  readonly storageBytes = computed(() => this.dashboard()?.storage_bytes ?? 0);
  readonly failuresThisWeek = computed(() => this.servers().reduce((sum, server) => sum + server.failures_7d, 0));
  readonly lastExportAt = computed(() => this.dashboard()?.last_export_at ?? null);

  readonly exportDue = computed(() => {
    const dashboard = this.dashboard();
    if (!dashboard) {
      return false;
    }
    const last = dashboard.last_export_at;
    return last === null || Date.now() - new Date(last).getTime() > EXPORT_STALE_DAYS * DAY_MS;
  });

  reload(): void {
    this.resource.reload();
  }
}
