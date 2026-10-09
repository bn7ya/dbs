import { Injectable, inject } from '@angular/core';
import { exhaustMap, takeWhile, timer, type Observable } from 'rxjs';

import { isFinished, type Job } from './job.types';
import { JobsApi } from './jobs.api';

export const JOB_POLL_MS = 2000;

@Injectable({ providedIn: 'root' })
export class JobWatcher {
  private readonly api = inject(JobsApi);

  // `exhaustMap`, not `switchMap`: a slow read is waited for, or a late backend would never be heard.
  watch(id: string): Observable<Job> {
    return timer(0, JOB_POLL_MS).pipe(
      exhaustMap(() => this.api.get(id)),
      takeWhile((job) => !isFinished(job), true),
    );
  }
}
