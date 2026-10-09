import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { rxResource, takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { finalize, switchMap } from 'rxjs';

import { apiErrorOf } from '@core/http/api-error';
import type { ApiError } from '@core/http/api.types';
import { JobWatcher } from '@core/jobs/job-watcher';
import type { Job } from '@core/jobs/job.types';
import { RedeployApi } from '../data/redeploy.api';
import { stepsOf, type RedeployRequest } from '../data/redeploy.types';

@Injectable()
export class RedeployStore {
  private readonly api = inject(RedeployApi);
  private readonly jobs = inject(JobWatcher);
  private readonly destroyRef = inject(DestroyRef);

  readonly source = signal<string | null>(null);

  private readonly serversResource = rxResource({
    params: () => this.source() ?? undefined,
    stream: () => this.api.servers(),
  });
  private readonly backupsResource = rxResource({
    params: () => this.source() ?? undefined,
    stream: ({ params }) => this.api.backups(params),
  });
  private readonly envResource = rxResource({
    params: () => this.source() ?? undefined,
    stream: ({ params }) => this.api.envVersions(params),
  });

  readonly targets = computed(() => {
    const source = this.source();
    const servers = this.serversResource.hasValue() ? this.serversResource.value().results : [];
    return servers.filter((server) => server.id !== source);
  });

  private readonly backupList = computed(() => (this.backupsResource.hasValue() ? this.backupsResource.value().results : []));
  readonly backups = computed(() => this.backupList().filter((backup) => backup.kind === 'dbs'));
  readonly archives = computed(() => this.backupList().filter((backup) => backup.kind === 'archive'));
  readonly envVersions = computed(() => (this.envResource.hasValue() ? this.envResource.value().results : []));

  readonly loading = computed(
    () => this.serversResource.isLoading() || this.backupsResource.isLoading() || this.envResource.isLoading(),
  );
  readonly loadError = computed(
    () =>
      apiErrorOf(this.serversResource.error()) ??
      apiErrorOf(this.backupsResource.error()) ??
      apiErrorOf(this.envResource.error()),
  );

  readonly running = signal(false);
  readonly runError = signal<ApiError | null>(null);
  readonly job = signal<Job | null>(null);
  readonly rehearsal = signal(false);
  readonly steps = computed(() => stepsOf(this.job()?.detail ?? {}));

  open(source: string | null): void {
    this.source.set(source);
  }

  clearError(): void {
    this.runError.set(null);
  }

  reload(): void {
    this.serversResource.reload();
    this.backupsResource.reload();
    this.envResource.reload();
  }

  run(request: RedeployRequest): void {
    if (this.running()) {
      return;
    }
    this.running.set(true);
    this.runError.set(null);
    this.job.set(null);
    this.rehearsal.set(request.rehearsal);
    this.api
      .run(request)
      .pipe(
        switchMap(({ activity }) => this.jobs.watch(activity)),
        finalize(() => this.running.set(false)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (job) => this.job.set(job),
        error: (error: unknown) => this.runError.set(error as ApiError),
      });
  }
}
