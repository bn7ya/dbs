import type { CollectResult } from '../data/backups.types';

export type CollectCounts = Pick<CollectResult, 'collected' | 'skipped'>;

export interface JobTarget {
  readonly server: string;
  readonly name: string;
}

export interface RestoreTarget extends JobTarget {
  readonly rehearse: boolean;
}

export interface Upload {
  readonly server: string;
  readonly name: string;
  readonly sent: number;
  readonly total: number;
}

export interface PlanRun {
  readonly server: string;
  readonly plan: string;
  readonly name: string;
}

export type RestoreProgress = 'rehearse' | 'restore';
