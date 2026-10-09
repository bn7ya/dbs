import type { Dashboard, DashboardServer } from '../data/dashboard.types';

export const NOW = new Date('2026-10-09T12:00:00Z');

export const WEB: DashboardServer = {
  id: '6f1c2a3e-0000-4000-8000-000000000001',
  name: 'Production web',
  host: 'web-1.example.com',
  check_status: 'ok',
  checked_at: '2026-10-09T11:00:00Z',
  last_backup: {
    id: 'b1',
    name: 'production-web-20261009-090000.dbs',
    size: 1_200_000,
    created_at: '2026-10-09T09:00:00Z',
    validation: 'verified',
  },
  next_plan_run: '2026-10-10T09:00:00Z',
  failures_7d: 2,
  storage_bytes: 5_000_000,
  health: { status: 'warn', checks: [], last_backup_at: '2026-10-09T09:00:00Z', generated_at: '2026-10-09T11:00:00Z' },
};

export const STAGING: DashboardServer = {
  ...WEB,
  id: '6f1c2a3e-0000-4000-8000-000000000002',
  name: 'Staging',
  host: 'staging.example.com',
  check_status: 'unknown',
  last_backup: null,
  next_plan_run: null,
  failures_7d: 1,
  storage_bytes: 0,
  health: null,
};

export const DASHBOARD: Dashboard = {
  servers: [WEB, STAGING],
  storage_bytes: 5_000_000,
  last_export_at: '2026-10-08T12:00:00Z',
  recent_failures: [
    {
      id: 41,
      action: 'backup.take',
      status: 'failed',
      target: 'production-web',
      error_code: 'ssh_unreachable',
      server: WEB.id,
      server_name: WEB.name,
      created_at: '2026-10-09T10:00:00Z',
    },
  ],
};
