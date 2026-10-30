import type { Page } from '@core/http/api.types';
import type { Job } from '@core/jobs/job.types';
import type { MoveApplication, MoveInventory, MoveServer, PlannedApplication } from '../data/relocation.types';

export const SOURCE = 'a1b2c3d4-1111-4a5b-8c9d-0e1f2a3b0001';

export const TARGET = 'a1b2c3d4-1111-4a5b-8c9d-0e1f2a3b0002';

export const OTHER = 'a1b2c3d4-1111-4a5b-8c9d-0e1f2a3b0003';

export const SHOP = 'c0ffee00-2222-4b6e-8f10-3c9d8e7f0001';

export const BLOG = 'c0ffee00-2222-4b6e-8f10-3c9d8e7f0002';

export const PLAN_ID = 31;

export const MOVE_ID = 32;

export const RESUMED_ID = 33;

export const SOURCE_SERVER: MoveServer = { id: SOURCE, name: 'Old web', host: '203.0.113.10', port: 22, username: 'deploy' };

export const TARGET_SERVER: MoveServer = { id: TARGET, name: 'New web', host: '203.0.113.20', port: 22, username: 'ops' };

export const OTHER_SERVER: MoveServer = { id: OTHER, name: 'Spare', host: '203.0.113.30', port: 2222, username: 'ops' };

export const SERVERS: readonly MoveServer[] = [SOURCE_SERVER, TARGET_SERVER, OTHER_SERVER];

export const APPLICATIONS: readonly MoveApplication[] = [
  { id: SHOP, name: 'Shop', kind: 'compose', engine: 'docker', project_dir: '/srv/shop' },
  { id: BLOG, name: 'Blog', kind: 'host', engine: '', project_dir: '/home/deploy/blog' },
];

export const PLANNED_SHOP: PlannedApplication = {
  application: SHOP,
  name: 'Shop',
  target_name: 'Shop',
  kind: 'compose',
  folder: { path: '/srv/shop', target: '/srv/shop', bytes: 52_428_800, excluded: ['db.sqlite3'] },
  git: { head: '0123456789abcdef0123', branch: 'main', remote: 'https://git.example.com/shop.git', dirty: 0 },
  images: [
    { ref: 'shop-web:latest', bytes: 314_572_800, on_target: false },
    { ref: 'postgres:16', bytes: 157_286_400, on_target: true },
  ],
  volumes: [
    { name: 'shop_media', bytes: 10_485_760, selected: true, reason: '' },
    { name: 'shop_pgdata', bytes: 1_048_576, selected: false, reason: 'database_volume' },
  ],
  binds: [],
  database: { vendor: 'postgresql', placement: 'compose_service', action: 'restore' },
  units: [],
  sites: [],
  python: {},
  blockers: [],
  notes: [{ code: 'compose_absolute_path' }],
};

export const PLANNED_BLOG: PlannedApplication = {
  application: BLOG,
  name: 'Blog',
  target_name: 'Blog',
  kind: 'host',
  folder: { path: '/home/deploy/blog', target: '/home/ops/blog', bytes: null, excluded: ['.venv'] },
  git: null,
  images: [],
  volumes: [],
  binds: [],
  database: { vendor: 'mysql', placement: 'remote', action: 'shared' },
  units: [{ name: 'blog.service' }],
  sites: [{ name: 'blog.conf' }],
  python: { action: 'rebuild', version: '3.11', target_version: '3.12' },
  blockers: [],
  notes: [{ code: 'python_version_differs', source: '3.11', target: '3.12' }],
};

export const INVENTORY: MoveInventory = {
  target: {
    system: { distribution: 'ubuntu', version: '24.04', architecture: 'amd64', supported: true },
    sudo: 'password',
  },
  packages: { packages: ['docker-ce', 'docker-compose-plugin', 'python3-venv'], repositories: ['/etc/apt/sources.list.d/docker.list'] },
  applications: [PLANNED_SHOP, PLANNED_BLOG],
  needs_sudo: { target: true, source: false },
  totals: { bytes: 377_487_360 },
  notes: [{ code: 'same_machine' }],
};

export const PLANNED: Job = {
  id: PLAN_ID,
  action: 'relocation.move',
  status: 'succeeded',
  detail: {
    rehearsal: true,
    inventory: INVENTORY,
    phases: [
      {
        phase: 'plan',
        status: 'succeeded',
        steps: [
          { step: 'connect', status: 'succeeded' },
          { step: 'inventory', status: 'succeeded' },
          { step: 'evaluate', status: 'succeeded' },
        ],
      },
    ],
    blockers: [],
  },
  error_code: '',
  finished_at: '2026-10-30T09:01:00Z',
  connection: null,
};

export const BLOCKED: Job = {
  ...PLANNED,
  status: 'failed',
  detail: {
    ...PLANNED.detail,
    blockers: [
      { code: 'target_folder_not_empty', application: 'Shop', path: '/srv/shop' },
      { code: 'sudo_missing' },
    ],
  },
  error_code: 'move_blocked',
};

export const MOVING: Job = {
  id: MOVE_ID,
  action: 'relocation.move',
  status: 'running',
  detail: {
    rehearsal: false,
    inventory: INVENTORY,
    phases: [
      { phase: 'plan', status: 'succeeded', steps: [{ step: 'connect', status: 'succeeded' }] },
      {
        phase: 'prepare',
        status: 'succeeded',
        steps: [
          { step: 'sudo_check', status: 'succeeded' },
          { step: 'packages', status: 'succeeded' },
        ],
      },
      {
        phase: 'application',
        name: 'Shop',
        target_name: 'Shop',
        status: 'running',
        steps: [
          { step: 'source_backup', status: 'succeeded' },
          { step: 'carry_image', key: 'shop-web:latest', status: 'running' },
          { step: 'register', status: 'pending' },
        ],
      },
    ],
    current: { step: 'carry_image', key: 'shop-web:latest', bytes: 157_286_400, total: 314_572_800 },
  },
  error_code: '',
  finished_at: null,
  connection: { state: 'alive', last_activity_at: '2026-10-30T09:05:00Z', bytes: 157_286_400 },
};

export const MOVE_STOPPED: Job = {
  ...MOVING,
  status: 'failed',
  detail: {
    ...MOVING.detail,
    current: undefined,
    leftovers: ['/home/ops/.dbs-staging/relocation-32'],
  },
  error_code: 'transfer_digest_mismatch',
  finished_at: '2026-10-30T09:07:00Z',
  connection: null,
};

export const MOVED: Job = {
  ...MOVING,
  status: 'succeeded',
  detail: {
    rehearsal: false,
    inventory: INVENTORY,
    phases: [
      {
        phase: 'application',
        name: 'Shop',
        target_name: 'Shop',
        status: 'succeeded',
        steps: [{ step: 'register', status: 'succeeded' }],
      },
    ],
    created_applications: [{ source: SHOP, target: 'd00d0000-3333-4c7d-9e8f-000000000001', name: 'Shop' }],
  },
  finished_at: '2026-10-30T09:20:00Z',
  connection: null,
};

export function pageOf<T>(results: readonly T[]): Page<T> {
  return { count: results.length, next: null, previous: null, results };
}
