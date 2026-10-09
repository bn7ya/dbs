export interface About {
  readonly version: string;
  readonly data_dir: string;
  readonly database: string;
  readonly backups_dir: string;
  readonly last_export_at: string | null;
}
