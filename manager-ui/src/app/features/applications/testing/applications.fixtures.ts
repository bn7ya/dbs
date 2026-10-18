import type { Page } from '@core/http/api.types';
import type {
  Application,
  ApplicationServer,
  ApplicationSummary,
  Candidate,
  CheckedApplication,
  Discovery,
  HostServer,
} from '../data/applications.types';

export const SERVER_ID = '0f3c2b9e-1111-4c4f-9a43-7b1d2f0c0001';

export const HOST: HostServer = {
  id: SERVER_ID,
  name: 'Production web',
  host: 'web-1.example.com',
  port: 22,
  username: 'deploy',
  connection_state: 'online',
  last_seen_at: '2026-09-30T12:00:00Z',
};

export const ON_SERVER: ApplicationServer = {
  id: SERVER_ID,
  name: 'Production web',
  host: 'web-1.example.com',
  port: 22,
  connection_state: 'online',
};

export const SUMMARY: ApplicationSummary = {
  id: '7a1d2f0c-2222-4c4f-9a43-0f3c2b9e0001',
  name: 'shop',
  server: ON_SERVER,
  kind: 'compose',
  engine: 'docker',
  compose_service: 'web',
  container_name: '',
  project_dir: '/srv/shop',
  last_check_status: 'ok',
  last_checked_at: '2026-09-30T12:00:00Z',
};

export const APPLICATION: Application = {
  id: SUMMARY.id,
  name: 'shop',
  server: ON_SERVER,
  kind: 'compose',
  engine: 'docker',
  compose_project: 'shop',
  compose_service: 'web',
  compose_files: [],
  container_name: '',
  project_dir: '/srv/shop',
  workdir: '/app',
  python_path: '/app/.venv/bin/python',
  manage_path: 'manage.py',
  settings_module: 'shop.settings',
  remote_backup_dir: '/var/backups/dbs',
  mounts: [
    { type: 'bind', source: '/srv/shop/backups', destination: '/var/backups/dbs', rw: true },
    { type: 'bind', source: '/srv/shop/media', destination: '/app/media', rw: false },
  ],
  file_roots: ['/app/media'],
  env_path: '/srv/shop/.env',
  env_location: 'host',
  has_backup_passphrase: true,
  last_check_status: 'ok',
  last_check_error: '',
  last_checked_at: '2026-09-30T12:00:00Z',
  last_check_report: {
    system: 'Linux 6.8.0',
    dbs_version: '0.8.0',
    dbs_error: '',
    python_suggestion: null,
    backup_command: true,
    env_file: true,
    roots: { '/app/media': true },
    remote_backup_dir: true,
    container: { engine: 'docker', version: '27.3.1', error: '', running: true },
    panel_schedule: { enabled: false, mode: '' },
  },
  last_health: { status: 'ok' },
  timeout_in_container: true,
  discovered_at: '2026-09-30T11:00:00Z',
  created_at: '2026-09-30T11:00:00Z',
  updated_at: '2026-09-30T12:00:00Z',
};

export const CHECKED: CheckedApplication = {
  ...APPLICATION,
  local_version: '0.8.0',
  remote_version: '0.8.0',
  installed: true,
  compatible: true,
};

export const COMPOSE_CANDIDATE: Candidate = {
  kind: 'compose',
  engine: 'docker',
  compose_project: 'shop',
  compose_service: 'web',
  compose_files: [],
  container_name: '',
  replicas: 2,
  running: true,
  project_dir: '/srv/shop',
  workdir: '/app',
  python_path: '/app/.venv/bin/python',
  python_paths: ['/app/.venv/bin/python', 'python3', 'python'],
  manage_path: 'manage.py',
  settings_module: 'shop.settings',
  remote_backup_dir: '/var/backups/dbs',
  backup_dir_on_host: '/srv/shop/backups',
  mounts: APPLICATION.mounts,
  file_roots: [{ path: '/app/media', on_host: '/srv/shop/media' }],
  env: [
    { path: '/srv/shop/.env', location: 'host', source: 'compose' },
    { path: '/app/.env', location: 'container', source: 'dbs' },
  ],
  dbs_version: '0.8.0',
  compatible: true,
  problems: [],
  score: 16,
};

export const HOST_CANDIDATE: Candidate = {
  kind: 'host',
  engine: '',
  compose_project: '',
  compose_service: '',
  compose_files: [],
  container_name: '',
  replicas: 1,
  running: true,
  project_dir: '/srv/shop',
  workdir: '',
  python_path: 'python3',
  python_paths: ['python3'],
  manage_path: 'manage.py',
  settings_module: '',
  remote_backup_dir: '',
  backup_dir_on_host: null,
  mounts: [],
  file_roots: [],
  env: [{ path: '/srv/shop/.env', location: 'host', source: 'folder' }],
  dbs_version: null,
  compatible: false,
  problems: ['dbs_missing'],
  score: 2,
};

export const DISCOVERY: Discovery = {
  folder: '/srv/shop',
  trusted: true,
  listing: { manage: true },
  candidates: [COMPOSE_CANDIDATE, HOST_CANDIDATE],
  folders: [],
};

export const NO_FOLDER: Discovery = {
  folder: '',
  trusted: false,
  listing: {},
  candidates: [],
  folders: ['/srv/shop', '/srv/blog'],
};

export function pageOf<T>(results: readonly T[], count = results.length): Page<T> {
  return { count, next: null, previous: null, results };
}
