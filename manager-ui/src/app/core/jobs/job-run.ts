import { DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { finalize, switchMap, type Observable } from 'rxjs';

import type { ApiError } from '@core/http/api.types';
import { JobWatcher } from '@core/jobs/job-watcher';
import type { Job, JobStarted } from '@core/jobs/job.types';

// One background job at a time, started and then followed; built inside a store, so it can inject.
export class JobRun {
  private readonly jobs = inject(JobWatcher);
  private readonly destroyRef = inject(DestroyRef);

  readonly busy = signal(false);
  readonly error = signal<ApiError | null>(null);
  readonly job = signal<Job | null>(null);
  readonly rehearsal = signal(false);

  start(rehearsal: boolean, started: Observable<JobStarted>): void {
    if (this.busy()) {
      return;
    }
    this.busy.set(true);
    this.error.set(null);
    this.job.set(null);
    this.rehearsal.set(rehearsal);
    started
      .pipe(
        switchMap(({ activity }) => this.jobs.watch(activity)),
        finalize(() => this.busy.set(false)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (job) => this.job.set(job),
        error: (error: unknown) => this.error.set(error as ApiError),
      });
  }

  clearError(): void {
    this.error.set(null);
  }

  forget(): void {
    this.job.set(null);
    this.error.set(null);
  }
}
