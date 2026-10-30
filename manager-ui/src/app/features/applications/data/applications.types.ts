import type { Page } from '@core/http/api.types';
import type { ConnectionState } from '@shared/connection-dot/connection-dot.types';

export type ApplicationKind = 'host' | 'compose' | 'container';

export type ContainerEngine = 'docker' | 'podman';

export type ApplicationEngine = '' | ContainerEngine;

export type EnvLocation = 'host' | 'container';

export type CheckStatus = 'unknown' | 'ok' | 'problem' | 'failed';

export interface Mount {
  readonly type: string;
  readonly source: string;
  readonly destination: string;
  readonly rw: boolean;
}

export interface ApplicationServer {
  readonly id: string;
  readonly name: string;
  readonly host: string;
  readonly port: number;
  readonly connection_state: ConnectionState;
}

export interface ApplicationSummary {
  readonly id: string;
  readonly name: string;
  readonly server: ApplicationServer;
  readonly kind: ApplicationKind;
  readonly engine: ApplicationEngine;
  readonly compose_service: string;
  readonly container_name: string;
  readonly project_dir: string;
  readonly last_check_status: CheckStatus;
  readonly last_checked_at: string | null;
}

export interface ApplicationSettings {
  readonly name: string;
  readonly kind: ApplicationKind;
  readonly engine: ApplicationEngine;
  readonly compose_project: string;
  readonly compose_service: string;
  readonly compose_files: readonly string[];
  readonly container_name: string;
  readonly project_dir: string;
  readonly workdir: string;
  readonly python_path: string;
  readonly manage_path: string;
  readonly settings_module: string;
  readonly remote_backup_dir: string;
  readonly mounts: readonly Mount[];
  readonly file_roots: readonly string[];
  readonly env_path: string;
  readonly env_location: EnvLocation;
}

export type DatabaseVendor = 'postgresql' | 'mysql' | 'mariadb' | 'sqlite' | 'other';

export type DatabaseRuns = 'compose' | 'this_server' | 'elsewhere' | 'file';

export type SettingsFrom = 'folder_env' | 'compose_env_file' | 'image' | 'environment';

export type CodeSource = 'git' | 'copied' | 'image';

export type ProcessManager = 'systemd' | 'systemd_user' | 'supervisor' | 'other';

export type WebServer = 'nginx' | 'other' | 'none';

export interface DeploymentProfile {
  readonly runs_in?: ApplicationKind;
  readonly engine?: ContainerEngine;
  readonly database?: DatabaseVendor;
  readonly database_runs?: DatabaseRuns;
  readonly settings_from?: SettingsFrom;
  readonly source?: CodeSource;
  readonly process_manager?: ProcessManager;
  readonly web_server?: WebServer;
}

export type DeploymentQuestion = keyof DeploymentProfile;

export interface DeploymentMismatch {
  readonly field: DeploymentQuestion;
  readonly said: string;
  readonly found: string;
}

export interface GitFacts {
  readonly head: string;
  readonly branch: string;
  readonly remote: string;
  readonly remote_has_credentials: boolean;
  readonly dirty: number | null;
}

export interface DatabaseFacts {
  readonly vendor: string;
  readonly host: string;
  readonly name: string;
}

export interface FoundFacts {
  readonly database: DatabaseFacts | null;
  readonly placement: string;
  readonly git: GitFacts | null;
}

export type CheckProblem =
  | 'engine_permission_denied'
  | 'engine_missing'
  | 'container_not_running'
  | 'dbs_missing'
  | 'dbs_too_old'
  | 'backup_command_missing'
  | 'env_file_missing'
  | 'root_missing'
  | 'backup_dir_not_mounted'
  | 'backup_dir_missing';

export interface ApplicationCreate extends ApplicationSettings {
  readonly server: string;
  readonly discovered: boolean;
  readonly deployment?: DeploymentProfile;
  readonly account_password?: string;
}

export interface ApplicationUpdate extends Partial<ApplicationSettings> {
  readonly deployment?: DeploymentProfile;
  readonly account_password?: string;
}

export interface PythonSuggestion {
  readonly python_path: string;
  readonly dbs_version: string;
}

export interface ContainerReport {
  readonly engine: ContainerEngine;
  readonly version: string | null;
  readonly error: string;
  readonly running: boolean;
}

export interface PanelSchedule {
  readonly enabled: boolean;
  readonly mode: string;
}

export interface ApplicationCheckReport {
  readonly system?: string | null;
  readonly dbs_version?: string | null;
  readonly dbs_error?: string;
  readonly python_suggestion?: PythonSuggestion | null;
  readonly backup_command?: boolean | null;
  readonly env_file?: boolean | null;
  readonly roots?: Readonly<Record<string, boolean>>;
  readonly remote_backup_dir?: boolean;
  readonly container?: ContainerReport;
  readonly panel_schedule?: PanelSchedule | null;
  readonly detected?: DeploymentProfile;
  readonly mismatches?: readonly DeploymentMismatch[];
  readonly problems?: readonly CheckProblem[];
  readonly facts?: FoundFacts;
}

export type HealthStatus = 'ok' | 'warn' | 'error';

export interface HealthReport {
  readonly status: HealthStatus;
}

export interface Application extends ApplicationSettings {
  readonly id: string;
  readonly server: ApplicationServer;
  readonly has_backup_passphrase: boolean;
  readonly last_check_status: CheckStatus;
  readonly last_check_error: string;
  readonly last_checked_at: string | null;
  readonly last_check_report: ApplicationCheckReport;
  readonly last_health: HealthReport | null;
  readonly timeout_in_container: boolean | null;
  readonly deployment: DeploymentProfile;
  readonly discovered_at: string | null;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface Compatibility {
  readonly local_version: string;
  readonly remote_version: string | null;
  readonly installed: boolean;
  readonly compatible: boolean;
}

export type CheckedApplication = Application & Compatibility;

export interface ApplicationListQuery {
  readonly search: string;
  readonly server: string | null;
  readonly page: number;
  readonly page_size: number;
}

export interface FileRootCandidate {
  readonly path: string;
  readonly on_host: string | null;
}

export type EnvSource = 'folder' | 'compose' | 'dbs';

export interface EnvCandidate {
  readonly path: string;
  readonly location: EnvLocation;
  readonly source: EnvSource;
}

export type DiscoveryProblem = 'container_not_running' | 'dbs_missing' | 'dbs_too_old' | 'backup_dir_not_mounted';

export interface Candidate {
  readonly kind: ApplicationKind;
  readonly engine: ApplicationEngine;
  readonly compose_project: string;
  readonly compose_service: string;
  readonly compose_files: readonly string[];
  readonly container_name: string;
  readonly replicas: number;
  readonly running: boolean;
  readonly project_dir: string;
  readonly workdir: string;
  readonly python_path: string;
  readonly python_paths: readonly string[];
  readonly manage_path: string;
  readonly settings_module: string;
  readonly remote_backup_dir: string;
  readonly backup_dir_on_host: string | null;
  readonly mounts: readonly Mount[];
  readonly file_roots: readonly FileRootCandidate[];
  readonly env: readonly EnvCandidate[];
  readonly dbs_version: string | null;
  readonly compatible: boolean;
  readonly problems: readonly DiscoveryProblem[];
  readonly score: number;
  readonly detected?: DeploymentProfile;
  readonly mismatches?: readonly DeploymentMismatch[];
  readonly facts?: FoundFacts;
}

export interface DiscoveryListing {
  readonly manage?: boolean;
}

export interface Discovery {
  readonly folder: string;
  readonly trusted: boolean;
  readonly listing: DiscoveryListing;
  readonly candidates: readonly Candidate[];
  readonly folders: readonly string[];
}

export interface DiscoverRequest {
  readonly server: string;
  readonly folder?: string;
  readonly deployment?: DeploymentProfile;
  readonly account_password?: string;
}

export interface BackupPassphrase {
  readonly passphrase: string;
}

export interface PassphraseCapture {
  readonly captured: boolean;
}

export interface HostServer {
  readonly id: string;
  readonly name: string;
  readonly host: string;
  readonly port: number;
  readonly username: string;
  readonly connection_state: ConnectionState;
  readonly last_seen_at: string | null;
}

export type RemoteEntryKind = 'file' | 'folder' | 'link' | 'other';

export interface RemoteEntry {
  readonly name: string;
  readonly path: string;
  readonly kind: RemoteEntryKind;
  readonly size: number | null;
  readonly modified: string | null;
}

export interface RemoteFolder extends Page<RemoteEntry> {
  readonly path: string;
  readonly parent: string | null;
  readonly home: string;
  readonly project: boolean;
  readonly truncated: boolean;
}

export interface BrowseQuery {
  readonly server: string;
  readonly path: string | null;
  readonly page: number;
  readonly page_size: number;
}
