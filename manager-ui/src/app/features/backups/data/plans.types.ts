export type PlanKind = 'dbs' | 'archive' | 'collect';

export const PLAN_SCHEDULES = {
  manual: null,
  hourly: 60,
  every3Hours: 180,
  every6Hours: 360,
  every12Hours: 720,
  daily: 1440,
  weekly: 10080,
} as const;

export type PlanSchedule = keyof typeof PLAN_SCHEDULES;

export type PlanInterval = (typeof PLAN_SCHEDULES)[PlanSchedule];

export function scheduleOf(interval: PlanInterval): PlanSchedule {
  const names = Object.keys(PLAN_SCHEDULES) as PlanSchedule[];
  return names.find((name) => PLAN_SCHEDULES[name] === interval) ?? 'manual';
}

export type PlanRunStatus = 'none' | 'succeeded' | 'failed';

export interface BackupPlan {
  readonly id: string;
  readonly application: string;
  readonly name: string;
  readonly kind: PlanKind;
  readonly paths: readonly string[];
  readonly pattern: string;
  readonly interval_minutes: PlanInterval;
  readonly keep: number;
  readonly keep_remote: number;
  readonly enabled: boolean;
  readonly anchor_at: string | null;
  readonly time_zone: string;
  readonly next_run_at: string | null;
  readonly last_run_at: string | null;
  readonly last_status: PlanRunStatus;
  readonly last_error_code: string;
  readonly created_at: string;
}

export interface PlanSettings {
  readonly name: string;
  readonly interval_minutes: PlanInterval;
  readonly keep: number;
  readonly keep_remote: number;
  readonly enabled: boolean;
  readonly paths: readonly string[];
  readonly pattern: string;
  readonly time_zone?: string;
  readonly anchor_at?: string;
}

export interface PlanPassword {
  readonly account_password?: string;
}

export interface PlanCreate extends PlanSettings, PlanPassword {
  readonly application: string;
  readonly kind: PlanKind;
}

export type PlanUpdate = Partial<PlanSettings> & PlanPassword;

export interface PlanListQuery {
  readonly application: string;
  readonly page: number;
  readonly page_size: number;
}

export interface Reschedule {
  readonly next_run_at: string;
}
