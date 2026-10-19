import type { JobStatus } from '@core/jobs/job.types';

export type BackupFileKind = 'dbs' | 'archive' | 'collected' | 'uploaded';

export type BackupValidation = 'structure_ok' | 'verified' | 'failed';

export interface BackupFile {
  readonly id: string;
  readonly application: string;
  readonly application_name: string;
  readonly server: string;
  readonly server_name: string;
  readonly kind: BackupFileKind;
  readonly name: string;
  readonly size: number;
  readonly sha256: string;
  readonly validation: BackupValidation;
  readonly validated_at: string | null;
  readonly failure: string;
  readonly remote_path: string;
  readonly taken_by: string | null;
  readonly plan: string | null;
  readonly plan_name: string | null;
  readonly created_at: string;
}

export interface DownloadLink {
  readonly url: string;
}

export type UploadEvent =
  | { readonly kind: 'progress'; readonly sent: number; readonly total: number }
  | { readonly kind: 'uploaded'; readonly file: BackupFile };

export interface BackupListQuery {
  readonly application: string | null;
  readonly page: number;
  readonly page_size: number;
}

export type VerifyOutcome = Extract<BackupValidation, 'verified' | 'failed'>;

export type RestoreMode = 'merge' | 'replace';

export interface RestoreRequest {
  readonly mode: RestoreMode;
  readonly rehearse: boolean;
  readonly account_password?: string;
  readonly application_name?: string;
  readonly target_application?: string;
}

export interface RestoreResult {
  readonly rehearse: boolean;
  readonly records: number | null;
  readonly files: number | null;
  readonly flushed: number | null;
  readonly healed: boolean;
  readonly copy_left?: string;
}

export interface CollectResult {
  readonly collected: number;
  readonly skipped: number;
  readonly size: number;
}

export interface ApplicationServer {
  readonly id: string;
  readonly name: string;
}

export interface ApplicationChoice {
  readonly id: string;
  readonly name: string;
  readonly server: ApplicationServer;
}

export interface DashboardApplication {
  readonly id: string;
  readonly name: string;
  readonly storage_bytes: number;
}

export interface DashboardServer {
  readonly id: string;
  readonly name: string;
  readonly applications: readonly DashboardApplication[];
}

export interface DashboardDisk {
  readonly total_bytes: number;
  readonly free_bytes: number;
  readonly low: boolean;
}

export interface Dashboard {
  readonly servers: readonly DashboardServer[];
  readonly storage_bytes: number;
  readonly disk: DashboardDisk | null;
}

export interface UnfinishedJob {
  readonly id: number;
  readonly action: string;
  readonly status: Extract<JobStatus, 'queued' | 'running'>;
  readonly target: string;
  readonly application: string | null;
  readonly detail: Readonly<Record<string, unknown>>;
}
