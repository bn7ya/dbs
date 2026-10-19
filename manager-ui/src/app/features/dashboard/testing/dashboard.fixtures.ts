import type { Dashboard, DashboardApplication, DashboardServer } from '../data/dashboard.types';

export const NOW = new Date('2026-10-09T12:00:00Z');

export const SHOP: DashboardApplication = {
  id: '7a1d2f0c-2222-4c4f-9a43-0f3c2b9e0001',
  name: 'shop',
  kind: 'compose',
  engine: 'docker',
  check_status: 'ok',
  checked_at: '2026-10-09T11:00:00Z',
  last_backup: {
    id: 'b1',
    name: 'shop-20261009-090000.dbs',
    size: 1_200_000,
    created_at: '2026-10-09T09:00:00Z',
    validation: 'verified',
  },
  next_plan_run: '2026-10-10T09:00:00Z',
  failures_7d: 2,
  storage_bytes: 5_000_000,
  health: { status: 'warn', checks: [] },
};

export const BLOG: DashboardApplication = {
  ...SHOP,
  id: '7a1d2f0c-2222-4c4f-9a43-0f3c2b9e0002',
  name: 'blog',
  kind: 'host',
  engine: '',
  check_status: 'unknown',
  last_backup: null,
  next_plan_run: null,
  failures_7d: 1,
  storage_bytes: 0,
  health: null,
};

export const WEB: DashboardServer = {
  id: '6f1c2a3e-0000-4000-8000-000000000001',
  name: 'Production web',
  host: 'web-1.example.com',
  check_status: 'ok',
  checked_at: '2026-10-09T11:00:00Z',
  connection_state: 'online',
  last_seen_at: '2026-10-09T11:58:00Z',
  applications: [SHOP, BLOG],
};

export const STAGING: DashboardServer = {
  ...WEB,
  id: '6f1c2a3e-0000-4000-8000-000000000002',
  name: 'Staging',
  host: 'staging.example.com',
  check_status: 'unknown',
  connection_state: 'offline',
  last_seen_at: '2026-10-09T09:00:00Z',
  applications: [],
};

export const DASHBOARD: Dashboard = {
  servers: [WEB, STAGING],
  storage_bytes: 5_000_000,
  last_export_at: '2026-10-08T12:00:00Z',
  key_store: 'keychain',
  recent_failures: [
    {
      id: 41,
      action: 'backup.take',
      status: 'failed',
      target: 'shop',
      error_code: 'ssh_unreachable',
      server: WEB.id,
      server_name: WEB.name,
      application: SHOP.id,
      application_name: SHOP.name,
      created_at: '2026-10-09T10:00:00Z',
    },
    {
      id: 40,
      action: 'server.check',
      status: 'failed',
      target: 'Staging',
      error_code: 'ssh_unreachable',
      server: STAGING.id,
      server_name: STAGING.name,
      application: null,
      application_name: null,
      created_at: '2026-10-09T08:00:00Z',
    },
  ],
};
