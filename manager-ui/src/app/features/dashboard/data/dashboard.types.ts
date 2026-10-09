export type DashboardCheckStatus = 'unknown' | 'ok' | 'problem' | 'failed';

export type HealthStatus = 'ok' | 'warn' | 'error';

export type DashboardValidation = 'structure_ok' | 'verified' | 'failed';

export interface DashboardBackup {
  readonly id: string;
  readonly name: string;
  readonly size: number;
  readonly created_at: string;
  readonly validation: DashboardValidation;
}

export interface HealthCheck {
  readonly name: string;
  readonly status: HealthStatus;
  readonly message: string;
}

export interface ServerHealth {
  readonly status: HealthStatus;
  readonly checks: readonly HealthCheck[];
  readonly last_backup_at: string | null;
  readonly generated_at: string;
}

export interface DashboardServer {
  readonly id: string;
  readonly name: string;
  readonly host: string;
  readonly check_status: DashboardCheckStatus;
  readonly checked_at: string | null;
  readonly last_backup: DashboardBackup | null;
  readonly next_plan_run: string | null;
  readonly failures_7d: number;
  readonly storage_bytes: number;
  readonly health: ServerHealth | null;
}

export interface DashboardFailure {
  readonly id: string;
  readonly action: string;
  readonly status: string;
  readonly target: string;
  readonly error_code: string;
  readonly server: string | null;
  readonly server_name: string | null;
  readonly created_at: string;
}

export interface Dashboard {
  readonly servers: readonly DashboardServer[];
  readonly storage_bytes: number;
  readonly last_export_at: string | null;
  readonly recent_failures: readonly DashboardFailure[];
}
