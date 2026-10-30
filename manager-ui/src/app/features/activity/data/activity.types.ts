export type ActivityStatus = 'queued' | 'running' | 'succeeded' | 'failed';

export const ACTIVITY_STATUSES: readonly ActivityStatus[] = ['queued', 'running', 'succeeded', 'failed'];

// What the filter offers. The codes a 0.7 server recorded, now an application's, are left out:
// their entries still read in words, and the filter does not offer one name twice.
export const ACTIVITY_ACTIONS: readonly string[] = [
  'server.create',
  'server.update',
  'server.delete',
  'server.check',
  'server.repin',
  'server.fingerprint',
  'server.host_key_confirm',
  'server.host_key_reject',
  'server.keypair',
  'server.merge',
  'application.create',
  'application.update',
  'application.delete',
  'application.check',
  'application.passphrase_reveal',
  'application.passphrase_capture',
  'application.discover',
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
  'plan.reschedule',
  'plan.pause',
  'plan.resume',
  'files.download',
  'files.upload',
  'files.create_folder',
  'files.delete',
  'env.pull',
  'env.reveal',
  'env.push',
  'relocation.move',
  'relocation.connect',
  'relocation.inventory',
  'relocation.evaluate',
  'relocation.sudo_check',
  'relocation.repositories',
  'relocation.packages',
  'relocation.engine_setup',
  'relocation.services',
  'relocation.users',
  'relocation.recheck',
  'relocation.source_backup',
  'relocation.carry_folder',
  'relocation.carry_extra',
  'relocation.carry_bind',
  'relocation.carry_image',
  'relocation.carry_volume',
  'relocation.backup_dir',
  'relocation.python',
  'relocation.database_create',
  'relocation.networks',
  'relocation.start',
  'relocation.register',
  'relocation.migrate',
  'relocation.restore',
  'relocation.install_units',
  'relocation.install_sites',
  'relocation.final_check',
  'relocation.copy_plans',
  'redeploy.run',
  'redeploy.check',
  'redeploy.source_backup',
  'redeploy.record_env',
  'redeploy.safety_backup',
  'redeploy.env',
  'redeploy.migrate',
  'redeploy.restore',
  'redeploy.archives',
  'redeploy.final_check',
  'redeploy.revert',
  'redeploy.revert_check',
  'redeploy.revert_env',
  'redeploy.revert_restore',
  'account.setup',
  'account.create',
  'account.role',
  'account.disable',
  'account.enable',
  'account.master',
  'account.two_factor_enrolled',
  'account.two_factor_reset',
  'account.recovery_codes',
  'account.password',
  'account.password_expire',
  'manager.export',
  'manager.import',
  'auth.sign_in',
  'auth.sign_in_failed',
  'auth.sign_out',
  'auth.recovery_code_used',
  'shell.session',
  'console.command',
  'application.deploy_steps',
  'redeploy.deploy',
  'deploy.check',
  'deploy.safety_backup',
  'deploy.record_env',
  'deploy.git_pull',
  'deploy.compose_pull',
  'deploy.compose_build',
  'deploy.compose_up',
  'deploy.restart',
  'deploy.systemd_user_restart',
  'deploy.pip_install',
  'deploy.migrate',
  'deploy.collectstatic',
  'deploy.final_check',
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
  readonly application: string | null;
  readonly application_name: string | null;
  readonly created_at: string;
  readonly started_at: string | null;
  readonly finished_at: string | null;
}

export interface ActivityQuery {
  readonly server?: string;
  readonly application?: string;
  readonly action?: string;
  readonly status?: ActivityStatus;
  readonly page: number;
  readonly page_size: number;
}
