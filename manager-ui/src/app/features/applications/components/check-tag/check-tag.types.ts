import type { StatusTagSeverity } from '@shared/status-tag/status-tag.types';

export interface CheckLook {
  readonly severity: StatusTagSeverity;
  readonly icon: string;
}
