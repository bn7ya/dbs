import type { Page } from '@core/http/api.types';
import type { Job } from '@core/jobs/job.types';
import type {
  DeployApplication,
  DeployStep,
  RedeployApplication,
  RedeployBackup,
  RedeployEnvVersion,
} from '../data/redeploy.types';

export const SOURCE = '5d2a7c11-2222-4b6e-8f10-3c9d8e7f0001';

export const TARGET = '5d2a7c11-2222-4b6e-8f10-3c9d8e7f0002';

export const DEPLOY_ID = 7;

export const MOVE_ID = 9;

export const REVERT_ID = 10;

export const PULL: DeployStep = { kind: 'git_pull', options: { remote: 'origin', branch: 'main' }, timeout_minutes: 5 };

export const BUILD: DeployStep = {
  kind: 'compose_build',
  options: { services: ['web', 'worker'], pull: true },
  timeout_minutes: 30,
};

export const UP: DeployStep = { kind: 'compose_up', options: { services: [] }, timeout_minutes: 10 };

export const MIGRATE: DeployStep = { kind: 'migrate', options: {}, timeout_minutes: 10 };

export const COMPOSE_APPLICATION: DeployApplication = {
  id: SOURCE,
  name: 'Shop',
  server: { id: 'b0a1c2d3-3333-4e5f-9a0b-1c2d3e4f0001', name: 'Production web' },
  kind: 'compose',
  project_dir: '/srv/shop',
  deploy_steps: [PULL, BUILD, UP, MIGRATE],
};

export const HOST_APPLICATION: DeployApplication = {
  ...COMPOSE_APPLICATION,
  kind: 'host',
  project_dir: '',
  deploy_steps: [],
};

export const APPLICATIONS: readonly RedeployApplication[] = [
  { id: SOURCE, name: 'Shop', server: { id: 's-1', name: 'Production web' } },
  { id: TARGET, name: 'Shop next', server: { id: 's-2', name: 'New web' } },
];

export const BACKUPS: readonly RedeployBackup[] = [
  { id: 'b-new', name: 'shop-20261009.dbs', kind: 'dbs', size: 10, created_at: '2026-10-09T09:00:00Z' },
  { id: 'a-media', name: 'shop-media.tar.gz', kind: 'archive', size: 10, created_at: '2026-10-09T08:00:00Z' },
  { id: 'b-old', name: 'shop-20261008.dbs', kind: 'dbs', size: 10, created_at: '2026-10-08T09:00:00Z' },
];

export const ENV_VERSIONS: readonly RedeployEnvVersion[] = [
  { id: 'env-new', path: '/srv/shop/.env', created_at: '2026-10-09T07:00:00Z' },
];

export const DEPLOYING: Job = {
  id: DEPLOY_ID,
  action: 'redeploy.deploy',
  status: 'running',
  detail: {
    rehearsal: false,
    before: { git_head: 'a1b2c3d4e5f6', image: 'sha256:0123456789abcdef' },
    steps: [
      { step: 'check', status: 'succeeded' },
      { step: 'safety_backup', status: 'succeeded' },
      { step: 'record_env', status: 'succeeded' },
      { step: 'git_pull', index: 0, status: 'running' },
      { step: 'compose_build', index: 1, status: 'pending' },
      { step: 'final_check', status: 'pending' },
    ],
  },
  error_code: '',
  finished_at: null,
  connection: { state: 'alive', last_activity_at: '2026-10-09T09:00:00Z', bytes: 2_000_000 },
};

export const DEPLOYED: Job = {
  ...DEPLOYING,
  status: 'succeeded',
  detail: {
    ...DEPLOYING.detail,
    after: { git_head: 'f6e5d4c3b2a1', image: 'sha256:fedcba9876543210' },
    steps: [
      { step: 'check', status: 'succeeded' },
      { step: 'git_pull', index: 0, status: 'succeeded' },
      { step: 'final_check', status: 'succeeded' },
    ],
  },
  finished_at: '2026-10-09T09:04:00Z',
  connection: null,
};

export const DEPLOY_STOPPED: Job = {
  ...DEPLOYING,
  status: 'failed',
  detail: {
    rehearsal: false,
    failed_step: 'compose_build',
    revertable: true,
    safety_backup: 'b-safety',
    steps: [
      { step: 'check', status: 'succeeded' },
      { step: 'git_pull', index: 0, status: 'succeeded' },
      { step: 'compose_build', index: 1, status: 'failed' },
      { step: 'final_check', status: 'skipped' },
    ],
  },
  error_code: 'remote_command_failed',
  finished_at: '2026-10-09T09:05:00Z',
  connection: null,
};

export const MOVING: Job = {
  id: MOVE_ID,
  action: 'redeploy.run',
  status: 'running',
  detail: {
    rehearsal: true,
    target_application: TARGET,
    steps: [
      { step: 'check', status: 'succeeded' },
      { step: 'source_backup', status: 'running' },
      { step: 'record_env', status: 'skipped' },
    ],
  },
  error_code: '',
  finished_at: null,
  connection: { state: 'alive', last_activity_at: '2026-10-09T09:00:00Z', bytes: 2_000_000 },
};

export const MOVE_STOPPED: Job = {
  id: MOVE_ID,
  action: 'redeploy.run',
  status: 'failed',
  detail: {
    rehearsal: false,
    target_application: TARGET,
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
  ...MOVE_STOPPED,
  status: 'succeeded',
  detail: {
    rehearsal: false,
    target_application: TARGET,
    fresh_backup: false,
    steps: [{ step: 'restore', status: 'succeeded' }],
  },
  error_code: '',
};

export const REHEARSED_WITHOUT_SOURCE: Job = {
  ...MOVED_FROM_CHOSEN,
  detail: {
    rehearsal: true,
    target_application: TARGET,
    source_reachable: false,
    steps: [{ step: 'restore', status: 'succeeded' }],
  },
};

export const REVERTED: Job = {
  id: REVERT_ID,
  action: 'redeploy.revert',
  status: 'succeeded',
  detail: {
    rehearsal: false,
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
