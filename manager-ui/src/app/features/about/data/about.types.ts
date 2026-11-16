export interface About {
  readonly version: string;
  readonly data_dir: string;
  readonly database: string;
  readonly backups_dir: string;
  readonly last_export_at: string | null;
}

export interface ManagerRelease {
  readonly current: string;
  readonly latest: string | null;
  readonly newer: boolean;
  readonly refusal: string | null;
  readonly busy: boolean;
}

export interface ManagerInstall {
  readonly version: string;
  readonly updated: boolean;
  readonly restarting: boolean;
}
