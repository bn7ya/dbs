export type AuthMethod = 'key' | 'password';

export type CheckStatus = 'unknown' | 'ok' | 'problem' | 'failed';

export interface ServerSummary {
  readonly id: string;
  readonly name: string;
  readonly host: string;
  readonly port: number;
  readonly username: string;
  readonly last_check_status: CheckStatus;
  readonly last_checked_at: string | null;
}

export interface CheckReport {
  readonly system?: string | null;
  readonly dbs_version?: string | null;
  readonly backup_command?: boolean | null;
  readonly env_file?: boolean | null;
  readonly roots?: Readonly<Record<string, boolean>>;
  readonly remote_backup_dir?: boolean;
}

export interface Server extends ServerSummary {
  readonly auth_method: AuthMethod;
  readonly has_private_key: boolean;
  readonly has_key_passphrase: boolean;
  readonly has_password: boolean;
  readonly host_key_type: string;
  readonly host_key_fingerprint: string;
  readonly project_dir: string;
  readonly python_path: string;
  readonly manage_path: string;
  readonly settings_module: string;
  readonly remote_backup_dir: string;
  readonly file_roots: readonly string[];
  readonly env_path: string;
  readonly last_check_error: string;
  readonly last_check_report: CheckReport;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface ServerSettings {
  readonly name: string;
  readonly host: string;
  readonly port: number;
  readonly username: string;
  readonly auth_method: AuthMethod;
  readonly private_key?: string;
  readonly key_passphrase?: string;
  readonly password?: string;
  readonly project_dir: string;
  readonly python_path: string;
  readonly manage_path: string;
  readonly settings_module: string;
  readonly remote_backup_dir: string;
  readonly file_roots: readonly string[];
  readonly env_path: string;
}

export interface ServerCreate extends ServerSettings {
  readonly host_key: string;
  readonly backup_passphrase?: string;
}

export interface ServerUpdate extends Partial<ServerSettings> {
  readonly account_password?: string;
}

export interface HostKeyTarget {
  readonly host: string;
  readonly port: number;
}

export interface HostKey {
  readonly key_type: string;
  readonly line: string;
  readonly fingerprint: string;
}

export interface HostKeyRepin {
  readonly host_key: string;
  readonly password: string;
}

export interface BackupPassphrase {
  readonly passphrase: string;
}

export interface ServerListQuery {
  readonly search: string;
  readonly page: number;
  readonly page_size: number;
}
