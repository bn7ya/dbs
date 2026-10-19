import { Injectable, computed, inject, linkedSignal, signal, type WritableSignal } from '@angular/core';
import { rxResource, toObservable, toSignal } from '@angular/core/rxjs-interop';
import { debounceTime, firstValueFrom, type Observable } from 'rxjs';

import { apiErrorOf } from '@core/http/api-error';
import type { ApiError, Page } from '@core/http/api.types';
import { ApplicationsApi } from '../data/applications.api';
import type {
  Application,
  ApplicationListQuery,
  ApplicationSummary,
  ApplicationUpdate,
  CheckedApplication,
  Compatibility,
} from '../data/applications.types';
import type { ListScope, ShownList } from './applications.store.types';

export const APPLICATION_PAGE_SIZES: number[] = [20, 50, 100];

const SEARCH_SETTLE_MS = 300;

@Injectable()
export class ApplicationsStore {
  private readonly api = inject(ApplicationsApi);

  private readonly scope = signal<ListScope | null>(null);

  readonly search = signal('');
  private readonly settledSearch = toSignal(toObservable(this.search).pipe(debounceTime(SEARCH_SETTLE_MS)), {
    initialValue: '',
  });

  readonly page = linkedSignal({ source: this.settledSearch, computation: () => 0 });
  readonly pageSize = signal(APPLICATION_PAGE_SIZES[0]);

  private readonly listQuery = computed<ApplicationListQuery | undefined>(() => {
    const scope = this.scope();
    return scope
      ? { search: this.settledSearch().trim(), server: scope.server, page: this.page() + 1, page_size: this.pageSize() }
      : undefined;
  });

  private readonly listResource = rxResource({
    params: () => this.listQuery(),
    stream: ({ params }) => this.api.list(params),
  });

  private readonly shownPage = linkedSignal<ShownList, Page<ApplicationSummary> | undefined>({
    source: () => ({
      open: this.listQuery() !== undefined,
      page: this.listResource.hasValue() ? this.listResource.value() : undefined,
    }),
    computation: ({ open, page }, previous) => page ?? (open ? previous?.value : undefined),
  });

  readonly applications = computed<ApplicationSummary[]>(() => [...(this.shownPage()?.results ?? [])]);
  readonly count = computed(() => this.shownPage()?.count ?? 0);
  readonly listLoading = this.listResource.isLoading;
  readonly listError = computed(() => apiErrorOf(this.listResource.error()));
  readonly listPending = computed(() => this.shownPage() === undefined && this.listLoading());
  readonly listEmpty = computed(() => this.shownPage()?.count === 0);
  readonly searching = computed(() => this.settledSearch().trim() !== '');

  openList(server: string | null): void {
    this.scope.set({ server });
  }

  closeList(): void {
    this.scope.set(null);
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

  private readonly applicationId = signal<string | undefined>(undefined);

  private readonly applicationResource = rxResource({
    params: () => this.applicationId(),
    stream: ({ params }) => this.api.get(params),
  });

  readonly application = computed<Application | undefined>(() =>
    this.applicationResource.hasValue() ? this.applicationResource.value() : undefined,
  );
  readonly applicationError = computed(() => apiErrorOf(this.applicationResource.error()));
  readonly applicationMissing = computed(() => this.applicationError()?.code === 'not_found');

  select(id: string | undefined): void {
    this.applicationId.set(id);
  }

  reloadApplication(): void {
    this.applicationResource.reload();
  }

  readonly checking = signal(false);

  readonly checkError = linkedSignal<string | undefined, ApiError | null>({
    source: this.applicationId,
    computation: () => null,
  });

  readonly versions = linkedSignal<string | undefined, Compatibility | null>({
    source: this.applicationId,
    computation: () => null,
  });

  readonly checkFailure = computed<string | null>(() => {
    const fresh = this.checkError();
    if (fresh) {
      return fresh.code;
    }
    const application = this.application();
    return application?.last_check_status === 'failed' && application.last_check_error
      ? application.last_check_error
      : null;
  });

  async check(): Promise<boolean> {
    const id = this.applicationId();
    if (!id) {
      return false;
    }
    this.checking.set(true);
    this.checkError.set(null);
    try {
      const checked = await firstValueFrom(this.api.check(id));
      this.applicationResource.set(checked);
      this.versions.set(compatibilityOf(checked));
      return true;
    } catch (error) {
      this.checkError.set(error as ApiError);
      this.applicationResource.reload();
      return false;
    } finally {
      this.checking.set(false);
    }
  }

  readonly saving = signal(false);
  readonly saveError = signal<ApiError | null>(null);

  resetForm(): void {
    this.saveError.set(null);
  }

  async update(changes: ApplicationUpdate): Promise<Application | null> {
    const id = this.applicationId();
    if (!id) {
      return null;
    }
    const saved = await this.run(this.api.update(id, changes), this.saving, this.saveError);
    if (saved && this.applicationId() === id) {
      this.applicationResource.set(saved);
    }
    return saved;
  }

  async usePython(pythonPath: string, accountPassword?: string): Promise<boolean> {
    const changes = { python_path: pythonPath, ...(accountPassword ? { account_password: accountPassword } : {}) };
    return (await this.update(changes)) !== null && (await this.check());
  }

  readonly revealing = signal(false);
  readonly revealError = signal<ApiError | null>(null);

  readonly passphrase = linkedSignal<string | undefined, string | null>({
    source: this.applicationId,
    computation: () => null,
  });

  async revealPassphrase(password: string): Promise<boolean> {
    const id = this.applicationId();
    if (!id) {
      return false;
    }
    const answer = await this.run(this.api.revealPassphrase(id, password), this.revealing, this.revealError);
    if (answer) {
      this.passphrase.set(answer.passphrase);
    }
    return answer !== null;
  }

  hidePassphrase(): void {
    this.passphrase.set(null);
  }

  readonly capturing = signal(false);
  readonly captureError = signal<ApiError | null>(null);

  async capturePassphrase(): Promise<boolean> {
    const id = this.applicationId();
    if (!id) {
      return false;
    }
    const answer = await this.run(this.api.capturePassphrase(id), this.capturing, this.captureError);
    if (answer?.captured) {
      this.applicationResource.reload();
    }
    return answer?.captured ?? false;
  }

  readonly deleting = signal(false);
  readonly deleteError = signal<ApiError | null>(null);

  async remove(password: string): Promise<boolean> {
    const id = this.applicationId();
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

  private async run<T>(
    request: Observable<T>,
    busy: WritableSignal<boolean>,
    failure: WritableSignal<ApiError | null>,
  ): Promise<T | null> {
    busy.set(true);
    failure.set(null);
    try {
      return await firstValueFrom(request);
    } catch (error) {
      failure.set(error as ApiError);
      return null;
    } finally {
      busy.set(false);
    }
  }
}

export function compatibilityOf(checked: CheckedApplication): Compatibility {
  return {
    local_version: checked.local_version,
    remote_version: checked.remote_version,
    installed: checked.installed,
    compatible: checked.compatible,
  };
}
