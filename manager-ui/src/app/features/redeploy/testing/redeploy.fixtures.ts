import type { Page } from '@core/http/api.types';
import type { Job } from '@core/jobs/job.types';
import type { RedeployBackup, RedeployEnvVersion, RedeployServer } from '../data/redeploy.types';

export const SOURCE = 'source-0000-4000-8000-000000000001';

export const MOVE_ID = 9;

export const REVERT_ID = 10;

export const SERVERS: readonly RedeployServer[] = [
  { id: SOURCE, name: 'Production web' },
  { id: 'target-0000-4000-8000-000000000002', name: 'New web' },
];

export const BACKUPS: readonly RedeployBackup[] = [
  { id: 'b-new', name: 'production-web-20261009.dbs', kind: 'dbs', size: 10, created_at: '2026-10-09T09:00:00Z' },
  { id: 'a-media', name: 'production-web-media.tar.gz', kind: 'archive', size: 10, created_at: '2026-10-09T08:00:00Z' },
  { id: 'b-old', name: 'production-web-20261008.dbs', kind: 'dbs', size: 10, created_at: '2026-10-08T09:00:00Z' },
];

export const ENV_VERSIONS: readonly RedeployEnvVersion[] = [
  { id: 'env-new', path: '/srv/app/.env', created_at: '2026-10-09T07:00:00Z' },
];

export const RUNNING: Job = {
  id: MOVE_ID,
  action: 'redeploy.run',
  status: 'running',
  detail: {
    steps: [
      { step: 'check', status: 'succeeded' },
      { step: 'source_backup', status: 'running' },
      { step: 'record_env', status: 'pending' },
    ],
  },
  error_code: '',
  finished_at: null,
  connection: { state: 'alive', last_activity_at: '2026-10-09T09:00:00Z', bytes: 2_000_000 },
};

export const STOPPED: Job = {
  id: MOVE_ID,
  action: 'redeploy.run',
  status: 'failed',
  detail: {
    rehearsal: false,
    failed_step: 'migrate',
    revertable: true,
    steps: [
      { step: 'check', status: 'succeeded' },
      { step: 'env', status: 'succeeded' },
      { step: 'migrate', status: 'failed' },
      { step: 'restore', status: 'skipped' },
    ],
  },
  error_code: 'remote_command_failed',
  finished_at: '2026-10-09T09:05:00Z',
  connection: null,
};

export const MOVED_FROM_CHOSEN: Job = {
  ...STOPPED,
  status: 'succeeded',
  detail: { rehearsal: false, fresh_backup: false, steps: [{ step: 'restore', status: 'succeeded' }] },
  error_code: '',
};

export const REVERTED: Job = {
  id: REVERT_ID,
  action: 'redeploy.revert',
  status: 'succeeded',
  detail: {
    steps: [
      { step: 'check', status: 'succeeded' },
      { step: 'env', status: 'succeeded' },
      { step: 'restore', status: 'succeeded' },
    ],
  },
  error_code: '',
  finished_at: '2026-10-09T09:09:00Z',
  connection: null,
};

export function pageOf<T>(results: readonly T[]): Page<T> {
  return { count: results.length, next: null, previous: null, results };
}
