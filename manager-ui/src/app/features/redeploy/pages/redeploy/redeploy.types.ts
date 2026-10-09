import type { StatusTagSeverity } from '@shared/status-tag/status-tag.types';

export interface StepLook {
  readonly severity: StatusTagSeverity;
  readonly icon: string;
}

export type Attempt = 'rehearsal' | 'real';
