import type { Page } from '@core/http/api.types';
import type { EnvComparison, EnvVersion } from '../data/envfiles.types';

export const SERVER_ID = '0f3c2b9e-1111-4c4f-9a43-7b1d2f0c0001';

export const ENV_PATH = '/srv/app/.env';

export const VERSION: EnvVersion = {
  id: '7a1e4c20-5555-4d3b-8c9f-1e2d3c4b0003',
  server: SERVER_ID,
  path: ENV_PATH,
  size: 1_200,
  keys: ['DEBUG', 'DATABASE_URL', 'SECRET_KEY'],
  source: 'pulled',
  created_at: '2026-09-30T12:00:00Z',
  taken_by: 'sara',
};

export const OLDER: EnvVersion = {
  ...VERSION,
  id: '7a1e4c20-5555-4d3b-8c9f-1e2d3c4b0002',
  size: 1_100,
  keys: ['DEBUG', 'DATABASE_URL', 'OLD_FLAG'],
  source: 'scheduled',
  created_at: '2026-09-29T03:00:00Z',
  taken_by: null,
};

export const OLDEST: EnvVersion = {
  ...VERSION,
  id: '7a1e4c20-5555-4d3b-8c9f-1e2d3c4b0001',
  size: 900,
  keys: ['DEBUG'],
  source: 'pushed',
  created_at: '2026-09-28T09:15:00Z',
};

export const CONTENT = 'DEBUG=false\nDATABASE_URL=postgres://app@db/app\nSECRET_KEY=s3cr3t\n';

export const COMPARISON: EnvComparison = {
  from: OLDER.id,
  to: VERSION.id,
  added: ['SECRET_KEY'],
  removed: ['OLD_FLAG'],
  changed: ['DEBUG'],
};

export function pageOf(results: readonly EnvVersion[], count = results.length): Page<EnvVersion> {
  return { count, next: null, previous: null, results };
}
