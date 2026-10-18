import { DestroyRef, Injectable, computed, inject, signal, type WritableSignal } from '@angular/core';
import { rxResource, takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { finalize, firstValueFrom, switchMap, type Observable } from 'rxjs';

import { apiErrorOf } from '@core/http/api-error';
import type { ApiError } from '@core/http/api.types';
import { JobWatcher } from '@core/jobs/job-watcher';
import type { Job } from '@core/jobs/job.types';
import { ApplicationsApi } from '../data/applications.api';
import type {
  Application,
  ApplicationCreate,
  ApplicationUpdate,
  Compatibility,
  Discovery,
  HostServer,
} from '../data/applications.types';
import { compatibilityOf } from './applications.store';

@Injectable()
export class ApplicationWizardStore {
  private readonly api = inject(ApplicationsApi);
  private readonly jobs = inject(JobWatcher);
  private readonly destroyRef = inject(DestroyRef);

  private readonly serverId = signal<string | null>(null);

  private readonly serverResource = rxResource({
    params: () => this.serverId() ?? undefined,
    stream: ({ params }) => this.api.server(params),
  });

  readonly server = computed<HostServer | undefined>(() =>
    this.serverResource.hasValue() ? this.serverResource.value() : undefined,
  );
  readonly serverError = computed(() => apiErrorOf(this.serverResource.error()));

  readonly discovery = signal<Discovery | null>(null);
  readonly application = signal<Application | null>(null);
  readonly versions = signal<Compatibility | null>(null);
  readonly captured = signal(false);
  readonly backupJob = signal<Job | null>(null);

  readonly discovering = signal(false);
  readonly discoverError = signal<ApiError | null>(null);
  readonly creating = signal(false);
  readonly createError = signal<ApiError | null>(null);
  readonly saving = signal(false);
  readonly saveError = signal<ApiError | null>(null);
  readonly checking = signal(false);
  readonly checkError = signal<ApiError | null>(null);
  readonly capturing = signal(false);
  readonly captureError = signal<ApiError | null>(null);
  readonly backingUp = signal(false);
  readonly backupError = signal<ApiError | null>(null);

  open(serverId: string | null): void {
    this.serverId.set(serverId);
  }

  async discover(folder: string, accountPassword?: string): Promise<Discovery | null> {
    const server = this.serverId();
    if (!server) {
      return null;
    }
    const request = {
      server,
      ...(folder ? { folder } : {}),
      ...(accountPassword ? { account_password: accountPassword } : {}),
    };
    const found = await this.run(this.api.discover(request), this.discovering, this.discoverError);
    if (found) {
      this.discovery.set(found);
    }
    return found;
  }

  async create(body: Omit<ApplicationCreate, 'server'>): Promise<Application | null> {
    const server = this.serverId();
    if (!server) {
      return null;
    }
    const created = await this.run(this.api.create({ ...body, server }), this.creating, this.createError);
    if (created) {
      this.application.set(created);
    }
    return created;
  }

  async update(changes: ApplicationUpdate): Promise<Application | null> {
    const id = this.application()?.id;
    if (!id) {
      return null;
    }
    const saved = await this.run(this.api.update(id, changes), this.saving, this.saveError);
    if (saved) {
      this.application.set(saved);
    }
    return saved;
  }

  async check(): Promise<boolean> {
    const id = this.application()?.id;
    if (!id) {
      return false;
    }
    const checked = await this.run(this.api.check(id), this.checking, this.checkError);
    if (checked) {
      this.application.set(checked);
      this.versions.set(compatibilityOf(checked));
    }
    return checked !== null;
  }

  async capturePassphrase(): Promise<boolean> {
    const id = this.application()?.id;
    if (!id) {
      return false;
    }
    const answer = await this.run(this.api.capturePassphrase(id), this.capturing, this.captureError);
    this.captured.set(answer?.captured ?? false);
    return this.captured();
  }

  takeBackup(): void {
    const id = this.application()?.id;
    if (!id || this.backingUp()) {
      return;
    }
    this.backingUp.set(true);
    this.backupError.set(null);
    this.backupJob.set(null);
    this.api
      .takeBackup(id)
      .pipe(
        switchMap(({ activity }) => this.jobs.watch(activity)),
        finalize(() => this.backingUp.set(false)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (job) => this.backupJob.set(job),
        error: (error: unknown) => this.backupError.set(error as ApiError),
      });
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
