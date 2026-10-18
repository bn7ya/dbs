import type { Capability, Identity } from '../data/auth.types';

export const EVERY_CAPABILITY: readonly Capability[] = [
  'accounts.manage',
  'servers.manage',
  'servers.check',
  'applications.manage',
  'applications.check',
  'applications.passphrase',
  'backups.take',
  'backups.verify',
  'backups.download',
  'backups.upload',
  'backups.delete',
  'backups.rehearse',
  'backups.restore',
  'plans.manage',
  'plans.run',
  'env.pull',
  'env.reveal',
  'env.push',
  'files.download',
  'files.change',
  'redeploy.rehearse',
  'redeploy.run',
  'shell.open',
  'console.run',
];

export const OPERATOR_CAPABILITIES: readonly Capability[] = [
  'console.run',
  'servers.check',
  'applications.check',
  'backups.take',
  'backups.verify',
  'backups.download',
  'backups.rehearse',
  'plans.run',
  'env.pull',
  'files.download',
  'redeploy.rehearse',
];

export const MASTER_ACCOUNT = {
  role: 'master',
  capabilities: EVERY_CAPABILITY,
  two_factor: true,
  recovery_codes_left: 10,
  password_changed_at: '2026-10-01T09:00:00Z',
  password_expires_at: '2026-10-31T09:00:00Z',
  password_change_required: false,
} as const satisfies Partial<Identity>;

export const MASTER: Identity = {
  id: 1,
  username: 'sara',
  email: '',
  first_name: '',
  last_name: '',
  is_staff: false,
  is_superuser: true,
  groups: [],
  permissions: [],
  ...MASTER_ACCOUNT,
};

export const OPERATOR: Identity = {
  ...MASTER,
  id: 2,
  username: 'omar',
  is_superuser: false,
  role: 'operator',
  capabilities: OPERATOR_CAPABILITIES,
};

export const VIEWER: Identity = {
  ...MASTER,
  id: 3,
  username: 'vera',
  is_superuser: false,
  role: 'viewer',
  capabilities: ['console.run'],
};
