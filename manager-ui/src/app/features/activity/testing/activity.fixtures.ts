import type { Page } from '@core/http/api.types';
import type { ActivityEntry } from '../data/activity.types';

export const SERVER_ID = '0f3c2b9e-1111-4c4f-9a43-7b1d2f0c0001';

export const APPLICATION_ID = '5d2a7c11-2222-4b6e-8f10-3c9d8e7f0001';

export const ENTRY: ActivityEntry = {
  id: 1,
  action: 'application.check',
  status: 'succeeded',
  target: '',
  detail: {},
  error_code: '',
  ip: '203.0.113.7',
  actor: 'sara',
  server: SERVER_ID,
  server_name: 'Production web',
  application: APPLICATION_ID,
  application_name: 'Shop',
  created_at: '2026-09-30T12:00:00Z',
  started_at: '2026-09-30T12:00:00Z',
  finished_at: '2026-09-30T12:00:04Z',
};

export const FAILED: ActivityEntry = {
  ...ENTRY,
  id: 2,
  status: 'failed',
  error_code: 'ssh_unreachable',
};

export const SERVER_ENTRY: ActivityEntry = {
  ...ENTRY,
  id: 3,
  action: 'server.check',
  application: null,
  application_name: null,
};

export const REMOVED: ActivityEntry = {
  ...ENTRY,
  id: 4,
  action: 'application.delete',
  application: null,
  application_name: 'Old shop',
  server: null,
  server_name: 'Retired web',
};

export function pageOf<T>(results: readonly T[], count = results.length): Page<T> {
  return { count, next: null, previous: null, results };
}
