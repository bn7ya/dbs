import type { AuthMethod, Server } from '../../data/servers.types';

export interface ServerFormData {
  readonly server: Server | null;
}

export type ServerFormStep = 'connection' | 'hostKey' | 'project';

export interface ServerDraft {
  readonly name: string;
  readonly host: string;
  readonly port: number | null;
  readonly username: string;
  readonly auth_method: AuthMethod;
  readonly private_key: string;
  readonly key_passphrase: string;
  readonly password: string;
  readonly project_dir: string;
  readonly python_path: string;
  readonly manage_path: string;
  readonly settings_module: string;
  readonly remote_backup_dir: string;
  readonly file_roots: readonly string[];
  readonly env_path: string;
  readonly backup_passphrase: string;
}

export type ServerDraftField = keyof ServerDraft | 'host_key';

export interface AuthMethodOption {
  readonly value: AuthMethod;
  readonly labelKey: string;
}
