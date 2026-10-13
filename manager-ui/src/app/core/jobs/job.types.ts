export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed';

export type JobConnectionState = 'alive' | 'lost';

export interface JobConnection {
  readonly state: JobConnectionState;
  readonly last_activity_at: string;
  readonly bytes: number;
}

export interface Job {
  readonly id: number;
  readonly action: string;
  readonly status: JobStatus;
  readonly detail: Readonly<Record<string, unknown>>;
  readonly error_code: string;
  readonly finished_at: string | null;
  readonly connection?: JobConnection | null;
}

export interface JobStarted {
  readonly activity: number;
}

export function isFinished(job: Job): boolean {
  return job.status === 'succeeded' || job.status === 'failed';
}
