import type { Account } from '../data/accounts.types';

export const SARA: Account = {
  id: 1,
  username: 'sara',
  role: 'master',
  is_active: true,
  two_factor: true,
  recovery_codes_left: 10,
  password_changed_at: '2026-10-01T09:00:00Z',
  password_expires_at: '2026-10-31T09:00:00Z',
  password_change_required: false,
  last_login: '2026-10-12T08:00:00Z',
  date_joined: '2026-09-01T09:00:00Z',
};

export const OMAR: Account = {
  ...SARA,
  id: 2,
  username: 'omar',
  role: 'operator',
  recovery_codes_left: 7,
  last_login: null,
};

export const NADIA: Account = {
  ...SARA,
  id: 3,
  username: 'nadia',
  role: 'viewer',
  is_active: false,
  two_factor: false,
  recovery_codes_left: 0,
  password_change_required: true,
};
