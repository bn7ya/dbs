import type { ConnectionState } from '@shared/connection-dot/connection-dot.types';

export type DashboardCheckStatus = 'unknown' | 'ok' | 'problem' | 'failed';

export type HealthStatus = 'ok' | 'warn' | 'error';

export type DashboardValidation = 'structure_ok' | 'verified' | 'failed';

export type ApplicationKind = 'host' | 'compose' | 'container';

export type ApplicationEngine = '' | 'docker' | 'podman';

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

export interface ApplicationHealth {
  readonly status: HealthStatus;
  readonly checks: readonly HealthCheck[];
}

export interface DashboardApplication {
  readonly id: string;
  readonly name: string;
  readonly kind: ApplicationKind;
  readonly engine: ApplicationEngine;
  readonly check_status: DashboardCheckStatus;
  readonly checked_at: string | null;
  readonly last_backup: DashboardBackup | null;
  readonly next_plan_run: string | null;
  readonly failures_7d: number;
  readonly storage_bytes: number;
  readonly health: ApplicationHealth | null;
}

export interface DashboardServer {
  readonly id: string;
  readonly name: string;
  readonly host: string;
  readonly check_status: DashboardCheckStatus;
  readonly checked_at: string | null;
  readonly connection_state: ConnectionState;
  readonly last_seen_at: string | null;
  readonly applications: readonly DashboardApplication[];
}

export interface DashboardFailure {
  readonly id: number;
  readonly action: string;
  readonly status: string;
  readonly target: string;
  readonly error_code: string;
  readonly server: string | null;
  readonly server_name: string | null;
  readonly application: string | null;
  readonly application_name: string | null;
  readonly created_at: string;
}

export type KeyStore = 'file' | 'keychain';

export interface Dashboard {
  readonly servers: readonly DashboardServer[];
  readonly storage_bytes: number;
  readonly last_export_at: string | null;
  readonly recent_failures: readonly DashboardFailure[];
  readonly key_store: KeyStore;
}
