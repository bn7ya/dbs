import type { StatusTagSeverity } from '@shared/status-tag/status-tag.types';

export interface StatusLook {
  readonly severity: StatusTagSeverity;
  readonly icon: string;
}

export interface FilterOption<T> {
  readonly label: string;
  readonly value: T;
}
