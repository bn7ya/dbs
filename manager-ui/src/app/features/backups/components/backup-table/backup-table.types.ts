import type { StatusTagSeverity } from '@shared/status-tag/status-tag.types';

export interface TagLook {
  readonly severity: StatusTagSeverity;
  readonly icon: string;
}

export type BackupColumn = 'name' | 'application' | 'server' | 'taken' | 'plan' | 'size' | 'check' | 'actions';
