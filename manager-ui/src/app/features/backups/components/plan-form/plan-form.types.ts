import type { BackupPlan, PlanKind, PlanSchedule, PlanSettings } from '../../data/plans.types';

export interface PlanFormData {
  readonly plan: BackupPlan | null;
  readonly name?: string;
  readonly kind?: PlanKind;
}

export interface Draft {
  readonly kind: PlanKind;
  readonly paths: readonly string[];
  readonly folder: string;
  readonly pattern: string;
  readonly name: string;
  readonly schedule: PlanSchedule;
  readonly firstDay: Date | null;
  readonly firstTime: Date | null;
  readonly timeZone: string;
  readonly keep: number | null;
  readonly keep_remote: number | null;
  readonly enabled: boolean;
}

export type DraftField = keyof PlanSettings | 'kind' | 'first_time';

export interface ScheduleOption {
  readonly value: PlanSchedule;
  readonly label: string;
}
