import type { StatusTagSeverity } from '@shared/status-tag/status-tag.types';

export interface StatusLook {
  readonly severity: StatusTagSeverity;
  readonly icon: string;
  readonly labelKey: string;
  readonly values?: Readonly<Record<string, string | number>>;
}
