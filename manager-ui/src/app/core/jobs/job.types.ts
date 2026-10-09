export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed';

export interface Job {
  readonly id: string;
  readonly action: string;
  readonly status: JobStatus;
  readonly detail: Readonly<Record<string, unknown>>;
  readonly error_code: string;
  readonly finished_at: string | null;
}

export interface JobStarted {
  readonly activity: string;
}

export function isFinished(job: Job): boolean {
  return job.status === 'succeeded' || job.status === 'failed';
}
