import { Injectable, computed, inject, linkedSignal, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { firstValueFrom } from 'rxjs';

import { apiErrorOf } from '@core/http/api-error';
import type { ApiError } from '@core/http/api.types';
import { errorText } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { Toaster } from '@shared/toaster/toaster';
import { EnvfilesApi } from '../data/envfiles.api';
import type { EnvComparison, EnvListQuery, EnvVersion, PullResult, PushResult } from '../data/envfiles.types';
import type { CompareFailure, Revealed, ShownPage, ShownSource } from './envfiles.store.types';

export const ENV_PAGE_SIZES: readonly number[] = [20, 50, 100];

@Injectable()
export class EnvfilesStore {
  private readonly api = inject(EnvfilesApi);
  private readonly toast = inject(Toaster);
  private readonly locale = inject(LocaleStore);

  private readonly isOpen = signal(false);

  readonly server = signal<string | null>(null);

  private readonly listed = computed(() => (this.isOpen() ? this.server() : null));

  open(server: string): void {
    this.hide();
    this.server.set(server);
    this.page.set(0);
    this.chosen.set(null);
    this.isOpen.set(true);
  }

  close(): void {
    this.hide();
    this.isOpen.set(false);
  }

  private readonly pathResource = rxResource({
    params: () => this.listed() ?? undefined,
    stream: ({ params }) => this.api.envPath(params),
  });

  readonly envPath = computed(() => (this.pathResource.hasValue() ? this.pathResource.value() : null));

  readonly noPath = computed(() => this.envPath() === '');

  readonly page = signal(0);
  readonly pageSize = signal(ENV_PAGE_SIZES[0]);

  private readonly query = computed<EnvListQuery | undefined>(() => {
    const server = this.listed();
    return server === null ? undefined : { server, page: this.page() + 1, page_size: this.pageSize() };
  });

  private readonly listResource = rxResource({
    params: () => this.query(),
    stream: ({ params }) => this.api.list(params),
  });

  private readonly shown = linkedSignal<ShownSource, ShownPage | undefined>({
    source: () => ({
      query: this.query(),
      page: this.listResource.hasValue() ? this.listResource.value() : undefined,
    }),
    computation: ({ query, page }, previous) => {
      if (query === undefined) {
        return undefined;
      }
      if (page !== undefined) {
        return { query, page };
      }
      const kept = previous?.value;
      return kept !== undefined && kept.query.server === query.server ? kept : undefined;
    },
  });

  readonly versions = computed<readonly EnvVersion[]>(() => this.shown()?.page.results ?? []);
  readonly count = computed(() => this.shown()?.page.count ?? 0);
  readonly loading = this.listResource.isLoading;
  readonly error = computed(() => apiErrorOf(this.listResource.error()));

  readonly pending = computed(() => this.shown() === undefined && this.loading());

  readonly empty = computed(() => this.shown()?.page.count === 0);

  goToPage(page: number, pageSize: number): void {
    this.hide();
    this.pageSize.set(pageSize);
    this.page.set(page);
  }

  reload(): void {
    this.listResource.reload();
  }

  private readonly chosen = signal<string | null>(null);

  readonly selected = computed<EnvVersion | null>(() => {
    const versions = this.versions();
    const chosen = this.chosen();
    return versions.find((version) => version.id === chosen) ?? versions[0] ?? null;
  });

  private readonly selectedId = computed(() => this.selected()?.id ?? null);

  select(version: EnvVersion): void {
    if (version.id !== this.selectedId()) {
      this.hide();
    }
    this.chosen.set(version.id);
  }

  private readonly position = computed(() => {
    const shown = this.shown();
    const id = this.selectedId();
    const index = shown?.page.results.findIndex((version) => version.id === id) ?? -1;
    return shown === undefined || index < 0 ? null : (shown.query.page - 1) * shown.query.page_size + index;
  });

  readonly hasPrevious = computed(() => {
    const position = this.position();
    return position !== null && position + 1 < this.count();
  });

  private readonly revealed = linkedSignal<string | null, Revealed | null>({
    source: this.selectedId,
    computation: () => null,
  });

  readonly content = computed(() => {
    const revealed = this.revealed();
    return revealed !== null && revealed.of === this.selectedId() ? revealed.content : null;
  });

  readonly revealError = signal<ApiError | null>(null);

  async reveal(version: EnvVersion, password: string): Promise<boolean> {
    this.revealError.set(null);
    try {
      const { content } = await firstValueFrom(this.api.reveal(version.id, password));
      if (this.isOpen() && this.selectedId() === version.id) {
        this.revealed.set({ of: version.id, content });
      }
      return true;
    } catch (error) {
      this.revealError.set(error as ApiError);
      return false;
    }
  }

  hide(): void {
    this.revealed.set(null);
  }

  private readonly comparisonState = signal<EnvComparison | null>(null);
  private readonly compareFailure = signal<CompareFailure | null>(null);
  private readonly comparingId = signal<string | null>(null);

  readonly comparison = computed(() => {
    const comparison = this.comparisonState();
    return comparison !== null && comparison.to === this.selectedId() ? comparison : null;
  });

  readonly compareError = computed(() => {
    const failure = this.compareFailure();
    return failure !== null && failure.of === this.selectedId() ? failure.error : null;
  });

  readonly comparing = computed(() => {
    const comparing = this.comparingId();
    return comparing !== null && comparing === this.selectedId();
  });

  async compare(): Promise<void> {
    const version = this.selected();
    if (version === null || this.comparingId() !== null) {
      return;
    }
    this.comparingId.set(version.id);
    this.compareFailure.set(null);
    try {
      const previous = await this.previousOf(version);
      if (previous !== null) {
        this.comparisonState.set(await firstValueFrom(this.api.compare(previous.id, version.id)));
      }
    } catch (error) {
      this.compareFailure.set({ of: version.id, error: error as ApiError });
    } finally {
      this.comparingId.set(null);
    }
  }

  private async previousOf(version: EnvVersion): Promise<EnvVersion | null> {
    const shown = this.shown();
    const rows = shown?.page.results ?? [];
    const index = rows.findIndex((row) => row.id === version.id);
    if (shown === undefined || index < 0) {
      return null;
    }
    const next = rows[index + 1];
    if (next !== undefined) {
      return next;
    }
    const position = (shown.query.page - 1) * shown.query.page_size + index + 1;
    if (position >= shown.page.count) {
      return null;
    }
    const found = await firstValueFrom(this.api.list({ server: shown.query.server, page: position + 1, page_size: 1 }));
    return found.results.find((row) => row.id !== version.id) ?? null;
  }

  private readonly pullingOn = signal<ReadonlySet<string>>(new Set());

  readonly pulling = computed(() => {
    const server = this.server();
    return server !== null && this.pullingOn().has(server);
  });

  async pull(): Promise<void> {
    const server = this.server();
    if (server === null || this.pullingOn().has(server)) {
      return;
    }
    this.pullingOn.update((servers) => new Set(servers).add(server));
    let result: PullResult;
    try {
      result = await firstValueFrom(this.api.pull(server));
    } catch (error) {
      this.toast.add({ severity: 'danger', summary: errorText(this.locale, error as ApiError) });
      return;
    } finally {
      this.pullingOn.update((servers) => {
        const rest = new Set(servers);
        rest.delete(server);
        return rest;
      });
    }
    if (result.created) {
      this.toast.add({ severity: 'success', summary: this.locale.translate('envfiles.pull.created') });
      this.showNewest(server, result.version);
    } else {
      this.toast.add({ severity: 'info', summary: this.locale.translate('envfiles.pull.unchanged') });
    }
  }

  readonly pushError = signal<ApiError | null>(null);

  async push(version: EnvVersion, password: string): Promise<boolean> {
    this.pushError.set(null);
    let result: PushResult;
    try {
      result = await firstValueFrom(this.api.push(version.id, password));
    } catch (error) {
      this.pushError.set(error as ApiError);
      return false;
    }
    this.toast.add({ severity: 'success', summary: this.locale.translate('envfiles.push.done') });
    this.showNewest(version.server, result.version);
    return true;
  }

  private showNewest(server: string, version: EnvVersion): void {
    if (this.server() !== server) {
      return;
    }
    this.hide();
    this.chosen.set(version.id);
    if (this.page() === 0) {
      this.listResource.reload();
    } else {
      this.page.set(0);
    }
  }
}
