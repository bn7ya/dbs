import type { StatusTagSeverity } from '../status-tag/status-tag.types';

export type StepStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped';

export interface ListedStep {
  readonly key: string;
  readonly label: string;
  readonly status: StepStatus;
  readonly statusLabel: string;
}

export interface StepLook {
  readonly severity: StatusTagSeverity;
  readonly icon: string;
}
