export type ActivityStatus = 'queued' | 'running' | 'succeeded' | 'failed';

export const ACTIVITY_STATUSES: readonly ActivityStatus[] = ['queued', 'running', 'succeeded', 'failed'];

export const ACTIVITY_ACTIONS: readonly string[] = [
  'server.create',
  'server.update',
  'server.delete',
  'server.check',
  'server.repin',
  'server.passphrase_reveal',
  'server.fingerprint',
  'server.keypair',
  'server.discover',
  'server.passphrase_capture',
  'backup.take',
  'backup.run',
  'backup.verify',
  'backup.restore',
  'backup.download',
  'backup.upload',
  'backup.delete',
  'backup.undo_delete',
  'backup.retention',
  'backup.expire',
  'plan.create',
  'plan.update',
  'plan.delete',
  'files.download',
  'files.upload',
  'files.create_folder',
  'files.delete',
  'env.pull',
  'env.reveal',
  'env.push',
  'redeploy.run',
  'redeploy.check',
  'redeploy.env',
  'redeploy.migrate',
  'redeploy.restore',
  'redeploy.archives',
  'redeploy.final_check',
  'account.setup',
  'manager.export',
  'manager.import',
  'auth.sign_in',
  'auth.sign_in_failed',
  'auth.sign_out',
];

export interface ActivityEntry {
  readonly id: number;
  readonly action: string;
  readonly status: ActivityStatus;
  readonly target: string;
  readonly detail: Readonly<Record<string, unknown>>;
  readonly error_code: string;
  readonly ip: string | null;
  readonly actor: string | null;
  readonly server: string | null;
  readonly server_name: string | null;
  readonly created_at: string;
  readonly started_at: string | null;
  readonly finished_at: string | null;
}

export interface ActivityQuery {
  readonly server?: string;
  readonly action?: string;
  readonly status?: ActivityStatus;
  readonly page: number;
  readonly page_size: number;
}
