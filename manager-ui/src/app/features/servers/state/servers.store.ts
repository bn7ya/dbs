import { Injectable, computed, inject, linkedSignal, signal } from '@angular/core';
import { rxResource, toObservable, toSignal } from '@angular/core/rxjs-interop';
import { debounceTime, firstValueFrom, forkJoin, map, of, switchMap, type Observable } from 'rxjs';

import { apiErrorOf } from '@core/http/api-error';
import type { ApiError, Page } from '@core/http/api.types';
import { ServersApi } from '../data/servers.api';
import type {
  HostKey,
  HostKeyConfirmation,
  HostKeyDecision,
  HostKeyTarget,
  Server,
  ServerListQuery,
  ServerSummary,
  ServerUpdate,
} from '../data/servers.types';
import type { TwinQuery } from './servers.store.types';

export const SERVER_PAGE_SIZES: number[] = [20, 50, 100];

const SEARCH_SETTLE_MS = 300;

const TWINS_PAGE_SIZE = 200;

@Injectable()
export class ServersStore {
  private readonly api = inject(ServersApi);

  private readonly listOpen = signal(false);

  readonly search = signal('');
  private readonly settledSearch = toSignal(toObservable(this.search).pipe(debounceTime(SEARCH_SETTLE_MS)), {
    initialValue: '',
  });

  readonly page = linkedSignal({ source: this.settledSearch, computation: () => 0 });
  readonly pageSize = signal(SERVER_PAGE_SIZES[0]);

  private readonly listQuery = computed<ServerListQuery | undefined>(() =>
    this.listOpen()
      ? { search: this.settledSearch().trim(), page: this.page() + 1, page_size: this.pageSize() }
      : undefined,
  );

  private readonly listResource = rxResource({
    params: () => this.listQuery(),
    stream: ({ params }) => this.api.list(params),
  });

  private readonly shownPage = linkedSignal<
    { readonly open: boolean; readonly page: Page<ServerSummary> | undefined },
    Page<ServerSummary> | undefined
  >({
    source: () => ({
      open: this.listQuery() !== undefined,
      page: this.listResource.hasValue() ? this.listResource.value() : undefined,
    }),
    computation: ({ open, page }, previous) => page ?? (open ? previous?.value : undefined),
  });

  readonly servers = computed<ServerSummary[]>(() => [...(this.shownPage()?.results ?? [])]);
  readonly count = computed(() => this.shownPage()?.count ?? 0);
  readonly listLoading = this.listResource.isLoading;
  readonly listError = computed(() => apiErrorOf(this.listResource.error()));

  readonly listPending = computed(() => this.shownPage() === undefined && this.listLoading());

  readonly searching = computed(() => this.settledSearch().trim() !== '');

  readonly listEmpty = computed(() => this.shownPage()?.count === 0);

  openList(): void {
    this.listOpen.set(true);
  }

  closeList(): void {
    this.listOpen.set(false);
  }

  setSearch(text: string): void {
    this.search.set(text);
  }

  goToPage(page: number, pageSize: number): void {
    this.pageSize.set(pageSize);
    this.page.set(page);
  }

  reloadList(): void {
    this.listResource.reload();
  }

  private readonly hostKeysResource = rxResource({
    params: () => this.listOpen() || undefined,
    stream: () => this.api.hostKeyConfirmations(),
  });

  readonly pendingHostKeys = computed<readonly HostKeyConfirmation[]>(() =>
    this.hostKeysResource.hasValue() ? (this.hostKeysResource.value()?.results ?? []) : [],
  );

  readonly decidingHostKeys = signal<ReadonlySet<string>>(new Set());
  readonly hostKeyDecisionError = signal<ApiError | null>(null);

  async decideHostKey(confirmation: HostKeyConfirmation, decision: HostKeyDecision): Promise<boolean> {
    this.decidingHostKeys.update((ids) => new Set(ids).add(confirmation.id));
    this.hostKeyDecisionError.set(null);
    try {
      await firstValueFrom(this.api.decideHostKey(confirmation.id, decision));
      return true;
    } catch (error) {
      this.hostKeyDecisionError.set(error as ApiError);
      return false;
    } finally {
      this.decidingHostKeys.update((ids) => new Set([...ids].filter((id) => id !== confirmation.id)));
      this.hostKeysResource.reload();
    }
  }

  private readonly serverId = signal<string | undefined>(undefined);

  private readonly serverResource = rxResource({
    params: () => this.serverId(),
    stream: ({ params }) => this.api.get(params),
  });

  readonly server = computed<Server | undefined>(() =>
    this.serverResource.hasValue() ? this.serverResource.value() : undefined,
  );
  readonly serverError = computed(() => apiErrorOf(this.serverResource.error()));
  readonly serverMissing = computed(() => this.serverError()?.code === 'not_found');

  select(id: string | undefined): void {
    this.serverId.set(id);
  }

  reloadServer(): void {
    this.serverResource.reload();
  }

  readonly saving = signal(false);
  readonly saveError = signal<ApiError | null>(null);

  readonly fetchingHostKey = signal(false);
  readonly hostKeyError = signal<ApiError | null>(null);

  resetForm(): void {
    this.saveError.set(null);
    this.hostKeyError.set(null);
  }

  async update(id: string, changes: ServerUpdate): Promise<Server | null> {
    this.saving.set(true);
    this.saveError.set(null);
    try {
      const saved = await firstValueFrom(this.api.update(id, changes));
      if (this.serverId() === id) {
        this.serverResource.set(saved);
      }
      return saved;
    } catch (error) {
      this.saveError.set(error as ApiError);
      return null;
    } finally {
      this.saving.set(false);
    }
  }

  async fetchHostKey(target: HostKeyTarget): Promise<HostKey | null> {
    this.fetchingHostKey.set(true);
    this.hostKeyError.set(null);
    try {
      return await firstValueFrom(this.api.fingerprint(target));
    } catch (error) {
      this.hostKeyError.set(error as ApiError);
      return null;
    } finally {
      this.fetchingHostKey.set(false);
    }
  }

  readonly checking = signal(false);

  readonly checkError = linkedSignal<string | undefined, ApiError | null>({
    source: this.serverId,
    computation: () => null,
  });

  readonly checkFailure = computed<string | null>(() => {
    const fresh = this.checkError();
    if (fresh) {
      return fresh.code;
    }
    const server = this.server();
    return server?.last_check_status === 'failed' && server.last_check_error
      ? server.last_check_error
      : null;
  });

  readonly hostKeyChanged = computed(() => this.checkFailure() === 'host_key_changed');

  async check(): Promise<boolean> {
    const id = this.serverId();
    if (!id) {
      return false;
    }
    this.checking.set(true);
    this.checkError.set(null);
    try {
      this.serverResource.set(await firstValueFrom(this.api.check(id)));
      return true;
    } catch (error) {
      this.checkError.set(error as ApiError);
      this.serverResource.reload();
      return false;
    } finally {
      this.checking.set(false);
    }
  }

  readonly repinning = signal(false);
  readonly repinError = signal<ApiError | null>(null);

  resetHostKeyReview(): void {
    this.hostKeyError.set(null);
    this.repinError.set(null);
  }

  async repinHostKey(hostKey: string, password: string): Promise<boolean> {
    const id = this.serverId();
    if (!id) {
      return false;
    }
    this.repinning.set(true);
    this.repinError.set(null);
    try {
      this.serverResource.set(
        await firstValueFrom(this.api.repinHostKey(id, { host_key: hostKey, password })),
      );
      this.checkError.set(null);
      return true;
    } catch (error) {
      this.repinError.set(error as ApiError);
      return false;
    } finally {
      this.repinning.set(false);
    }
  }

  readonly publicKey = linkedSignal<string | undefined, string | null>({
    source: this.serverId,
    computation: () => null,
  });
  readonly readingKey = signal(false);
  readonly keyError = signal<ApiError | null>(null);

  async readPublicKey(): Promise<boolean> {
    const id = this.serverId();
    if (!id) {
      return false;
    }
    this.readingKey.set(true);
    this.keyError.set(null);
    try {
      this.publicKey.set((await firstValueFrom(this.api.publicKey(id))).public_key);
      return true;
    } catch (error) {
      this.keyError.set(error as ApiError);
      return false;
    } finally {
      this.readingKey.set(false);
    }
  }

  hidePublicKey(): void {
    this.publicKey.set(null);
  }

  private readonly twinsWanted = signal(false);

  private readonly twinQuery = computed<TwinQuery | undefined>(
    () => {
      const server = this.server();
      return server && this.twinsWanted()
        ? { id: server.id, host: server.host, port: server.port, username: server.username, hostKey: server.host_key }
        : undefined;
    },
    { equal: (before, after) => JSON.stringify(before) === JSON.stringify(after) },
  );

  private readonly twinsResource = rxResource({
    params: () => this.twinQuery(),
    stream: ({ params }) => this.twinsOf(params),
  });

  readonly twins = computed<readonly Server[]>(() =>
    this.twinsResource.hasValue() ? (this.twinsResource.value() ?? []) : [],
  );

  watchTwins(wanted: boolean): void {
    this.twinsWanted.set(wanted);
  }

  readonly merging = signal(false);
  readonly mergeError = signal<ApiError | null>(null);

  async merge(into: string, password: string): Promise<boolean> {
    const id = this.serverId();
    if (!id) {
      return false;
    }
    this.merging.set(true);
    this.mergeError.set(null);
    try {
      await firstValueFrom(this.api.merge(id, { into, account_password: password }));
      return true;
    } catch (error) {
      this.mergeError.set(error as ApiError);
      return false;
    } finally {
      this.merging.set(false);
    }
  }

  readonly deleting = signal(false);
  readonly deleteError = signal<ApiError | null>(null);

  async remove(password: string): Promise<boolean> {
    const id = this.serverId();
    if (!id) {
      return false;
    }
    this.deleting.set(true);
    this.deleteError.set(null);
    try {
      await firstValueFrom(this.api.remove(id, password));
      return true;
    } catch (error) {
      this.deleteError.set(error as ApiError);
      return false;
    } finally {
      this.deleting.set(false);
    }
  }

  // The list leaves out host keys, so each server at the same address is read once to compare them.
  private twinsOf(query: TwinQuery): Observable<readonly Server[]> {
    return this.api.list({ search: query.host, page: 1, page_size: TWINS_PAGE_SIZE }).pipe(
      map((page) =>
        page.results.filter(
          (other) =>
            other.id !== query.id &&
            other.host === query.host &&
            other.port === query.port &&
            other.username === query.username,
        ),
      ),
      switchMap((same) =>
        same.length === 0
          ? of([])
          : forkJoin(same.map((other) => this.api.get(other.id))).pipe(
              map((servers) => servers.filter((other) => other.host_key === query.hostKey)),
            ),
      ),
    );
  }
}
