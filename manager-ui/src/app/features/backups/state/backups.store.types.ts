import type { Job } from '@core/jobs/job.types';
import type { CollectResult } from '../data/backups.types';

export type CollectCounts = Pick<CollectResult, 'collected' | 'skipped'>;

export interface BackupScope {
  readonly every: boolean;
  readonly application: string | null;
}

export interface JobTarget {
  readonly application: string;
  readonly name: string;
}

export interface RestoreTarget extends JobTarget {
  readonly rehearse: boolean;
}

export interface Upload {
  readonly application: string;
  readonly name: string;
  readonly sent: number;
  readonly total: number;
}

export type RestoreProgress = 'rehearse' | 'restore';

export interface LiveJob {
  readonly application: string;
  readonly job: Job;
}

export interface StoredApplication {
  readonly id: string;
  readonly name: string;
  readonly server: string;
  readonly serverName: string;
  readonly bytes: number;
}

export interface Storage {
  readonly total: number;
  readonly applications: readonly StoredApplication[];
}
