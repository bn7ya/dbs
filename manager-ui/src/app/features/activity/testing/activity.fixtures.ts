import type { Page } from '@core/http/api.types';
import type { ActivityEntry } from '../data/activity.types';

export const SERVER_ID = '0f3c2b9e-1111-4c4f-9a43-7b1d2f0c0001';

export const ENTRY: ActivityEntry = {
  id: '7a1e0c55-2222-4d1b-8f00-9c3e5b7d0001',
  action: 'server.check',
  status: 'succeeded',
  target: '',
  detail: {},
  error_code: '',
  ip: '203.0.113.7',
  actor: 'sara',
  server: SERVER_ID,
  server_name: 'Production web',
  created_at: '2026-09-30T12:00:00Z',
  started_at: '2026-09-30T12:00:00Z',
  finished_at: '2026-09-30T12:00:04Z',
};

export const FAILED: ActivityEntry = {
  ...ENTRY,
  id: '7a1e0c55-2222-4d1b-8f00-9c3e5b7d0002',
  status: 'failed',
  error_code: 'ssh_unreachable',
};

export function pageOf<T>(results: readonly T[], count = results.length): Page<T> {
  return { count, next: null, previous: null, results };
}
