export type Role = 'master' | 'admin' | 'operator' | 'viewer';

export type Capability =
  | 'accounts.manage'
  | 'servers.manage'
  | 'servers.check'
  | 'servers.passphrase'
  | 'applications.manage'
  | 'applications.check'
  | 'applications.passphrase'
  | 'backups.take'
  | 'backups.verify'
  | 'backups.download'
  | 'backups.upload'
  | 'backups.delete'
  | 'backups.rehearse'
  | 'backups.restore'
  | 'plans.manage'
  | 'plans.run'
  | 'env.pull'
  | 'env.reveal'
  | 'env.push'
  | 'files.download'
  | 'files.change'
  | 'redeploy.rehearse'
  | 'redeploy.run'
  | 'shell.open'
  | 'console.run';

export interface Identity {
  readonly id: number;
  readonly username: string;
  readonly email: string;
  readonly first_name: string;
  readonly last_name: string;
  readonly is_staff: boolean;
  readonly is_superuser: boolean;
  readonly groups: readonly string[];
  readonly permissions: readonly string[];
  readonly role: Role | null;
  readonly capabilities: readonly Capability[];
  readonly two_factor: boolean;
  readonly recovery_codes_left: number;
  readonly password_changed_at: string;
  readonly password_expires_at: string;
  readonly password_change_required: boolean;
}

export interface Credentials {
  readonly username: string;
  readonly password: string;
}

export type SignInStepName = 'code' | 'enroll';

export interface SignInStep {
  readonly step: SignInStepName;
}

export interface SecondFactor {
  readonly code?: string;
  readonly recovery_code?: string;
}

export interface Enrollment {
  readonly secret: string;
  readonly uri: string;
  readonly issuer: string;
  readonly username: string;
}

export interface SignedIn {
  readonly identity: Identity;
  readonly recovery_codes: readonly string[];
}

export interface PasswordChange {
  readonly current_password: string;
  readonly new_password: string;
}

export interface RecoveryCodes {
  readonly recovery_codes: readonly string[];
}

export interface CsrfAnswer {
  readonly csrf_token: string;
}
