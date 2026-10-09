import type { Page } from '@core/http/api.types';
import type { Job } from '@core/jobs/job.types';
import type { BackupFile, BackupPlan } from '../data/backups.types';

export const SERVER_ID = '0f3c2b9e-1111-4c4f-9a43-7b1d2f0c0001';

export const FILE: BackupFile = {
  id: '5b2d8e10-3333-4a6c-b1f2-0d9e8c7b0001',
  server: SERVER_ID,
  server_name: 'production-web',
  kind: 'dbs',
  name: 'production-web-20260930-120000.dbs',
  size: 1_200_000,
  sha256: '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08',
  validation: 'structure_ok',
  validated_at: null,
  remote_path: '/var/backups/dbs/production-web-20260930-120000.dbs',
  taken_by: 'sara',
  plan: null,
  plan_name: null,
  created_at: '2026-09-30T12:00:00Z',
};

export const PLAN: BackupPlan = {
  id: '3c9a7f42-4444-4b7e-a2d1-6e5f4a3b0001',
  server: SERVER_ID,
  name: 'django-dbs',
  kind: 'dbs',
  paths: [],
  pattern: '',
  interval_minutes: 1440,
  keep: 7,
  keep_remote: 1,
  enabled: true,
  next_run_at: '2026-10-01T12:00:00Z',
  last_run_at: '2026-09-30T12:00:00Z',
  last_status: 'succeeded',
  last_error_code: '',
  created_at: '2026-09-01T12:00:00Z',
};

export const MANUAL_PLAN: BackupPlan = {
  ...PLAN,
  id: '3c9a7f42-4444-4b7e-a2d1-6e5f4a3b0002',
  name: 'Before upgrade',
  interval_minutes: null,
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
  name: 'production-web-media-20260930-120000.tar.gz',
  remote_path: '/var/backups/dbs/production-web-media-20260930-120000.tar.gz',
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
  keep: 14,
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
  name: 'production-web-20260901-030000.dbs',
  remote_path: '',
};

export const VERIFIED: BackupFile = {
  ...FILE,
  id: '5b2d8e10-3333-4a6c-b1f2-0d9e8c7b0002',
  name: 'production-web-20260929-120000.dbs',
  validation: 'verified',
  validated_at: '2026-09-30T13:00:00Z',
  taken_by: null,
  plan: PLAN.id,
  plan_name: PLAN.name,
};

export const JOB_ID = '7a1e0c55-2222-4d1b-8f00-9c3e5b7d0009';

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

export function pageOf<T>(results: readonly T[], count = results.length): Page<T> {
  return { count, next: null, previous: null, results };
}
