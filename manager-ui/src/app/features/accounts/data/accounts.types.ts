import type { Role } from '@core/auth/data/auth.types';

export type AssignableRole = Exclude<Role, 'master'>;

export interface Account {
  readonly id: number;
  readonly username: string;
  readonly role: Role;
  readonly is_active: boolean;
  readonly two_factor: boolean;
  readonly recovery_codes_left: number;
  readonly password_changed_at: string;
  readonly password_expires_at: string;
  readonly password_change_required: boolean;
  readonly last_login: string | null;
  readonly date_joined: string;
}

export interface AccountCreate {
  readonly username: string;
  readonly password: string;
  readonly role: AssignableRole;
}

export interface AccountUpdate {
  readonly role?: AssignableRole;
  readonly is_active?: boolean;
}

export interface HandOver {
  readonly password: string;
  readonly code: string;
}
