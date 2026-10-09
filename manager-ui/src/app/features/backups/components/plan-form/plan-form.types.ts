import type { BackupKind, BackupPlan, PlanSchedule, PlanSettings } from '../../data/backups.types';

export interface PlanFormData {
  readonly plan: BackupPlan | null;
  readonly name?: string;
  readonly kind?: BackupKind;
}

export interface Draft {
  readonly kind: BackupKind;
  readonly paths: readonly string[];
  readonly folder: string;
  readonly pattern: string;
  readonly name: string;
  readonly schedule: PlanSchedule;
  readonly keep: number | null;
  readonly keep_remote: number | null;
  readonly enabled: boolean;
}

export type DraftField = keyof PlanSettings | 'kind';

export interface ScheduleOption {
  readonly value: PlanSchedule;
  readonly label: string;
}
