export interface SnippetHostKey {
  readonly type: string;
  readonly fingerprint: string;
}

export interface ConnectionSnippet {
  readonly hostname: string;
  readonly ssh_user: string;
  readonly project_dir: string;
  readonly python_path: string;
  readonly manage_path: string;
  readonly settings_module: string;
  readonly remote_backup_dir: string;
  readonly file_roots: readonly string[];
  readonly env_path: string;
  readonly dbs_version: string;
  readonly host_keys: readonly SnippetHostKey[];
}

export type SnippetError = 'snippet_invalid' | 'snippet_not_dbs';

export type SnippetParse =
  | { readonly snippet: ConnectionSnippet; readonly error: null }
  | { readonly snippet: null; readonly error: SnippetError | null };
