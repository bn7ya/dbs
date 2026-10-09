import type { Page } from '@core/http/api.types';
import type { Server, ServerCreate, ServerSummary } from '../data/servers.types';

export const SUMMARY: ServerSummary = {
  id: '0f3c2b9e-1111-4c4f-9a43-7b1d2f0c0001',
  name: 'Production web',
  host: 'web-1.example.com',
  port: 22,
  username: 'deploy',
  last_check_status: 'ok',
  last_checked_at: '2026-09-30T12:00:00Z',
};

export const SERVER: Server = {
  ...SUMMARY,
  auth_method: 'key',
  has_private_key: true,
  has_key_passphrase: false,
  has_password: false,
  host_key_type: 'ssh-ed25519',
  host_key_fingerprint: 'SHA256:abc',
  project_dir: '/srv/app',
  python_path: 'python3',
  manage_path: 'manage.py',
  settings_module: '',
  remote_backup_dir: '/var/backups/dbs',
  file_roots: ['/srv/app/media'],
  env_path: '',
  last_check_error: '',
  last_check_report: { system: 'Linux', dbs_version: '0.4.0', backup_command: true },
  created_at: '2026-09-01T00:00:00Z',
  updated_at: '2026-09-30T12:00:00Z',
};

export const CREATE: ServerCreate = {
  name: 'Production web',
  host: 'web-1.example.com',
  port: 22,
  username: 'deploy',
  auth_method: 'key',
  private_key: '-----BEGIN OPENSSH PRIVATE KEY-----',
  host_key: 'web-1.example.com ssh-ed25519 AAAA',
  project_dir: '/srv/app',
  python_path: 'python3',
  manage_path: 'manage.py',
  settings_module: '',
  remote_backup_dir: '/var/backups/dbs',
  file_roots: [],
  env_path: '',
};

export function pageOf<T>(results: readonly T[], count = results.length): Page<T> {
  return { count, next: null, previous: null, results };
}
