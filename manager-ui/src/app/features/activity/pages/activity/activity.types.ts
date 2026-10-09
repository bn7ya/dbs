import type { TagSeverity } from 'primeng/types/tag';

export interface StatusLook {
  readonly severity: TagSeverity;
  readonly icon: string;
}

export interface FilterOption<T> {
  readonly label: string;
  readonly value: T;
}
