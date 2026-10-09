import { DestroyRef, Injectable, inject, signal, type WritableSignal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { finalize, firstValueFrom, last, switchMap, type Observable } from 'rxjs';

import type { ApiError } from '@core/http/api.types';
import { JobWatcher } from '@core/jobs/job-watcher';
import type { Job } from '@core/jobs/job.types';
import { ServersApi } from '../data/servers.api';
import type {
  CheckedServer,
  CreatedServer,
  Discovery,
  HostKey,
  HostKeyTarget,
  ProjectSettings,
  ServerCreate,
} from '../data/servers.types';

@Injectable()
export class ServerWizardStore {
  private readonly api = inject(ServersApi);
  private readonly jobs = inject(JobWatcher);
  private readonly destroyRef = inject(DestroyRef);

  readonly server = signal<CreatedServer | null>(null);
  readonly publicKey = signal<string | null>(null);
  readonly checked = signal<CheckedServer | null>(null);
  readonly captured = signal(false);
  readonly backupJob = signal<Job | null>(null);

  readonly fetchingHostKey = signal(false);
  readonly hostKeyError = signal<ApiError | null>(null);
  readonly creating = signal(false);
  readonly createError = signal<ApiError | null>(null);
  readonly readingKey = signal(false);
  readonly keyError = signal<ApiError | null>(null);
  readonly discovering = signal(false);
  readonly discoverError = signal<ApiError | null>(null);
  readonly savingProject = signal(false);
  readonly projectError = signal<ApiError | null>(null);
  readonly checking = signal(false);
  readonly checkError = signal<ApiError | null>(null);
  readonly capturing = signal(false);
  readonly captureError = signal<ApiError | null>(null);
  readonly backingUp = signal(false);
  readonly backupError = signal<ApiError | null>(null);

  fetchHostKey(target: HostKeyTarget): Promise<HostKey | null> {
    return this.run(this.api.fingerprint(target), this.fetchingHostKey, this.hostKeyError);
  }

  async create(body: ServerCreate): Promise<CreatedServer | null> {
    const created = await this.run(this.api.create(body), this.creating, this.createError);
    if (created) {
      this.server.set(created);
      this.publicKey.set(created.public_key ?? null);
    }
    return created;
  }

  async rereadPublicKey(): Promise<void> {
    const id = this.server()?.id;
    if (id) {
      const found = await this.run(this.api.publicKey(id), this.readingKey, this.keyError);
      if (found) {
        this.publicKey.set(found.public_key);
      }
    }
  }

  discover(): Promise<Discovery | null> {
    const id = this.server()?.id;
    return id ? this.run(this.api.discover(id), this.discovering, this.discoverError) : Promise.resolve(null);
  }

  async saveProject(settings: ProjectSettings): Promise<boolean> {
    const id = this.server()?.id;
    if (!id) {
      return false;
    }
    const saved = await this.run(this.api.update(id, settings), this.savingProject, this.projectError);
    if (saved) {
      this.server.update((current) => (current ? { ...current, ...saved } : current));
    }
    return saved !== null;
  }

  async check(): Promise<CheckedServer | null> {
    const id = this.server()?.id;
    if (!id) {
      return null;
    }
    const checked = await this.run(this.api.check(id), this.checking, this.checkError);
    this.checked.set(checked);
    return checked;
  }

  async capturePassphrase(): Promise<boolean> {
    const id = this.server()?.id;
    if (!id) {
      return false;
    }
    const answer = await this.run(this.api.capturePassphrase(id), this.capturing, this.captureError);
    this.captured.set(answer?.captured ?? false);
    return this.captured();
  }

  takeBackup(): void {
    const id = this.server()?.id;
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
        last(),
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
