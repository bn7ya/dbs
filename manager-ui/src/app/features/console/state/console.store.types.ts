import type { ApiError } from '@core/http/api.types';
import type { Job } from '@core/jobs/job.types';

export type ConsoleEntryState = 'running' | 'done' | 'password' | 'refused';

export interface ConsoleEntry {
  readonly id: number;
  readonly line: string;
  readonly state: ConsoleEntryState;
  readonly exitCode: number | null;
  readonly output: string;
  readonly activities: readonly number[];
  readonly errorCode: string;
  readonly error: ApiError | null;
}

export interface ConsoleJob {
  readonly id: number;
  readonly job: Job | null;
  readonly error: ApiError | null;
}
