export type SignInChoice = 'generate' | 'key' | 'password';

export type WizardStep = 'snippet' | 'connection' | 'signIn' | 'project' | 'check' | 'passphrase' | 'backup';

export type FingerprintMatch = 'match' | 'mismatch';

export interface WizardDraft {
  readonly name: string;
  readonly host: string;
  readonly port: number | null;
  readonly username: string;
  readonly sign_in: SignInChoice;
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
}

export type WizardField = keyof WizardDraft | 'snippet' | 'host_key';
