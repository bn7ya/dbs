export interface ServerRecord {
  id: string;
  name: string;
  host_key_fingerprint: string;
  last_check_status: string;
}

export interface DeploymentRecord {
  runs_in?: string;
  engine?: string;
  database?: string;
  database_runs?: string;
  settings_from?: string;
  source?: string;
  process_manager?: string;
  web_server?: string;
}

export interface ApplicationRecord {
  id: string;
  name: string;
  server: { id: string; name: string };
  kind: string;
  engine: string;
  compose_service: string;
  project_dir: string;
  python_path: string;
  remote_backup_dir: string;
  file_roots: string[];
  env_path: string;
  deployment: DeploymentRecord;
  has_backup_passphrase: boolean;
  last_check_status: string;
  deploy_steps: unknown[];
}

export interface Page<T> {
  count: number;
  results: T[];
}

export interface BackupRecord {
  id: string;
  name: string;
  kind: string;
  validation: string;
}

export interface JobStarted {
  activity: number;
}

export interface PlanRecord {
  id: string;
  name: string;
  enabled: boolean;
  time_zone: string;
  next_run_at: string | null;
}

export interface ActivityRecord {
  id: number;
  action: string;
  status: string;
  target: string;
  error_code: string;
  server_name: string | null;
  application_name: string | null;
}
