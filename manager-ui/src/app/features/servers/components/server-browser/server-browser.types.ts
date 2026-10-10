export type BrowseMode = 'folder' | 'file';

export type BrowsedField = 'project_dir' | 'remote_backup_dir' | 'env_path' | 'file_roots';

export interface BrowsedPaths {
  readonly project_dir: string;
  readonly remote_backup_dir: string;
  readonly env_path: string;
}

export interface ServerBrowserData {
  readonly serverId: string;
  readonly start: string | null;
  readonly mode: BrowseMode;
  readonly projects: readonly string[];
}
