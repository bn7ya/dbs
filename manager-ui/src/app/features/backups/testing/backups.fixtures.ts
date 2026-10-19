import type { Page } from '@core/http/api.types';
import type { Job } from '@core/jobs/job.types';
import type { ApplicationChoice, BackupFile, Dashboard, UnfinishedJob } from '../data/backups.types';
import type { BackupPlan } from '../data/plans.types';

export const APPLICATION_ID = '7a1c2b9e-2222-4c4f-9a43-7b1d2f0c0001';

export const OTHER_APPLICATION_ID = '7a1c2b9e-2222-4c4f-9a43-7b1d2f0c0002';

export const SERVER_ID = '0f3c2b9e-1111-4c4f-9a43-7b1d2f0c0001';

export const OTHER_SERVER_ID = '0f3c2b9e-1111-4c4f-9a43-7b1d2f0c0002';

export const FILE: BackupFile = {
  id: '5b2d8e10-3333-4a6c-b1f2-0d9e8c7b0001',
  application: APPLICATION_ID,
  application_name: 'shop',
  server: SERVER_ID,
  server_name: 'production-web',
  kind: 'dbs',
  name: 'shop-20260930-120000.dbs',
  size: 1_200_000,
  sha256: '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08',
  validation: 'structure_ok',
  validated_at: null,
  failure: '',
  remote_path: '/var/backups/dbs/shop-20260930-120000.dbs',
  taken_by: 'sara',
  plan: null,
  plan_name: null,
  created_at: '2026-09-30T12:00:00Z',
};

export const PLAN: BackupPlan = {
  id: '3c9a7f42-4444-4b7e-a2d1-6e5f4a3b0001',
  application: APPLICATION_ID,
  name: 'django-dbs',
  kind: 'dbs',
  paths: [],
  pattern: '',
  interval_minutes: 1440,
  keep: 3,
  keep_remote: 1,
  enabled: true,
  anchor_at: '2026-09-01T00:00:00Z',
  time_zone: 'UTC',
  next_run_at: '2026-10-01T00:00:00Z',
  last_run_at: '2026-09-30T00:00:00Z',
  last_status: 'succeeded',
  last_error_code: '',
  created_at: '2026-09-01T12:00:00Z',
};

export const RIYADH_PLAN: BackupPlan = {
  ...PLAN,
  id: '3c9a7f42-4444-4b7e-a2d1-6e5f4a3b0005',
  name: 'Nightly',
  time_zone: 'Asia/Riyadh',
  anchor_at: '2026-09-01T23:00:00Z',
  next_run_at: '2026-10-01T23:00:00Z',
};

export const PAUSED_PLAN: BackupPlan = {
  ...PLAN,
  id: '3c9a7f42-4444-4b7e-a2d1-6e5f4a3b0006',
  name: 'Hourly',
  interval_minutes: 60,
  enabled: false,
  next_run_at: null,
  last_status: 'none',
  last_run_at: null,
};

export const MANUAL_PLAN: BackupPlan = {
  ...PLAN,
  id: '3c9a7f42-4444-4b7e-a2d1-6e5f4a3b0002',
  name: 'Before upgrade',
  interval_minutes: null,
  anchor_at: null,
  next_run_at: null,
  last_status: 'failed',
  last_error_code: 'ssh_unreachable',
};

export const ARCHIVE_PLAN: BackupPlan = {
  ...PLAN,
  id: '3c9a7f42-4444-4b7e-a2d1-6e5f4a3b0003',
  name: 'Media',
  kind: 'archive',
  paths: ['/srv/app/media', '/srv/app/uploads'],
  interval_minutes: 10080,
};

export const ARCHIVE_FILE: BackupFile = {
  ...FILE,
  id: '5b2d8e10-3333-4a6c-b1f2-0d9e8c7b0003',
  kind: 'archive',
  name: 'shop-media-20260930-120000.tar.gz',
  remote_path: '/var/backups/dbs/shop-media-20260930-120000.tar.gz',
  taken_by: null,
  plan: ARCHIVE_PLAN.id,
  plan_name: ARCHIVE_PLAN.name,
};

export const COLLECT_PLAN: BackupPlan = {
  ...PLAN,
  id: '3c9a7f42-4444-4b7e-a2d1-6e5f4a3b0004',
  name: 'Database dumps',
  kind: 'collect',
  paths: ['/var/backups/postgres'],
  pattern: '*.sql.gz',
  keep: 4,
  keep_remote: 0,
};

export const COLLECTED_FILE: BackupFile = {
  ...FILE,
  id: '5b2d8e10-3333-4a6c-b1f2-0d9e8c7b0004',
  kind: 'collected',
  name: 'app-2026-09-30.sql.gz',
  remote_path: '/var/backups/postgres/app-2026-09-30.sql.gz',
  taken_by: null,
  plan: COLLECT_PLAN.id,
  plan_name: COLLECT_PLAN.name,
};

export const UPLOADED_FILE: BackupFile = {
  ...FILE,
  id: '5b2d8e10-3333-4a6c-b1f2-0d9e8c7b0005',
  kind: 'uploaded',
  name: 'shop-20260901-030000.dbs',
  remote_path: '',
};

export const VERIFIED: BackupFile = {
  ...FILE,
  id: '5b2d8e10-3333-4a6c-b1f2-0d9e8c7b0002',
  name: 'shop-20260929-120000.dbs',
  validation: 'verified',
  validated_at: '2026-09-30T13:00:00Z',
  taken_by: null,
  plan: PLAN.id,
  plan_name: PLAN.name,
};

export const QUARANTINED: BackupFile = {
  ...FILE,
  id: '5b2d8e10-3333-4a6c-b1f2-0d9e8c7b0006',
  name: 'shop-20260928-120000.dbs.quarantined',
  validation: 'failed',
  validated_at: '2026-09-28T12:01:00Z',
  failure: 'The bytes that arrived are not the ones the server sent.',
};

export const BLOG_FILE: BackupFile = {
  ...FILE,
  id: '5b2d8e10-3333-4a6c-b1f2-0d9e8c7b0007',
  application: OTHER_APPLICATION_ID,
  application_name: 'blog',
  server: OTHER_SERVER_ID,
  server_name: 'staging-web',
  name: 'blog-20260930-120000.dbs',
};

export const SHOP: ApplicationChoice = { id: APPLICATION_ID, name: 'shop', server: { id: SERVER_ID, name: 'production-web' } };

export const BLOG: ApplicationChoice = {
  id: OTHER_APPLICATION_ID,
  name: 'blog',
  server: { id: OTHER_SERVER_ID, name: 'staging-web' },
};

export const APPLICATIONS: readonly ApplicationChoice[] = [SHOP, BLOG];

export const DASHBOARD: Dashboard = {
  storage_bytes: 5_400_000,
  disk: { total_bytes: 100_000_000_000, free_bytes: 62_000_000_000, low: false },
  servers: [
    { id: SERVER_ID, name: 'production-web', applications: [{ id: APPLICATION_ID, name: 'shop', storage_bytes: 1_400_000 }] },
    {
      id: OTHER_SERVER_ID,
      name: 'staging-web',
      applications: [{ id: OTHER_APPLICATION_ID, name: 'blog', storage_bytes: 4_000_000 }],
    },
  ],
};

export const JOB_ID = 9;

export function jobOf(action: string, finish: Partial<Job> = {}): Job {
  return {
    id: JOB_ID,
    action,
    status: 'succeeded',
    detail: {},
    error_code: '',
    finished_at: '2026-09-30T12:01:00Z',
    ...finish,
  };
}

export function unfinished(action: string, entry: Partial<UnfinishedJob> = {}): UnfinishedJob {
  return {
    id: JOB_ID,
    action,
    status: 'running',
    target: FILE.name,
    application: APPLICATION_ID,
    detail: {},
    ...entry,
  };
}

export function pageOf<T>(results: readonly T[], count = results.length): Page<T> {
  return { count, next: null, previous: null, results };
}
