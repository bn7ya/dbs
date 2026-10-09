import type { JobStatus } from '@core/jobs/job.types';

export type BackupKind = 'dbs' | 'archive' | 'collect';

export type BackupFileKind = Exclude<BackupKind, 'collect'> | 'collected' | 'uploaded';

export type BackupValidation = 'structure_ok' | 'verified' | 'failed';

export interface BackupFile {
  readonly id: string;
  readonly server: string;
  readonly server_name: string;
  readonly kind: BackupFileKind;
  readonly name: string;
  readonly size: number;
  readonly sha256: string;
  readonly validation: BackupValidation;
  readonly validated_at: string | null;
  readonly remote_path: string;
  readonly taken_by: string | null;
  readonly plan: string | null;
  readonly plan_name: string | null;
  readonly created_at: string;
}

export type UploadEvent =
  | { readonly kind: 'progress'; readonly sent: number; readonly total: number }
  | { readonly kind: 'uploaded'; readonly file: BackupFile };

export interface BackupListQuery {
  readonly server: string;
  readonly page: number;
  readonly page_size: number;
}

export type VerifyOutcome = Extract<BackupValidation, 'verified' | 'failed'>;

export type RestoreMode = 'merge' | 'replace';

export interface RestoreRequest {
  readonly mode: RestoreMode;
  readonly rehearse: boolean;
  readonly account_password?: string;
  readonly server_name?: string;
}

export interface RestoreResult {
  readonly rehearse: boolean;
  readonly records: number | null;
  readonly files: number | null;
  readonly flushed: number | null;
  readonly healed: boolean;
  readonly copy_left?: string;
}

export type BackupWarning = 'files_changed';

export interface CollectResult {
  readonly collected: number;
  readonly skipped: number;
  readonly size: number;
}

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
  readonly server: string;
  readonly name: string;
  readonly kind: BackupKind;
  readonly paths: readonly string[];
  readonly pattern: string;
  readonly interval_minutes: PlanInterval;
  readonly keep: number;
  readonly keep_remote: number;
  readonly enabled: boolean;
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
}

export interface PlanPassword {
  readonly account_password?: string;
}

export interface PlanCreate extends PlanSettings, PlanPassword {
  readonly server: string;
  readonly kind: BackupKind;
}

export type PlanUpdate = Partial<PlanSettings> & PlanPassword;

export interface PlanListQuery {
  readonly server: string;
  readonly page: number;
  readonly page_size: number;
}

export interface UnfinishedJob {
  readonly id: string;
  readonly action: string;
  readonly status: Extract<JobStatus, 'queued' | 'running'>;
  readonly target: string;
  readonly detail: Readonly<Record<string, unknown>>;
}
