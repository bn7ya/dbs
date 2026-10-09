import type { StatusTagSeverity } from '@shared/status-tag/status-tag.types';

export interface CheckStatusLook {
  readonly severity: StatusTagSeverity;
  readonly icon: string;
}
