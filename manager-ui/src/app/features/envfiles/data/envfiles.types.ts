export type EnvSource = 'pulled' | 'pushed' | 'scheduled';

export interface EnvVersion {
  readonly id: string;
  readonly application: string;
  readonly path: string;
  readonly size: number;
  readonly keys: readonly string[];
  readonly source: EnvSource;
  readonly created_at: string;
  readonly taken_by: string | null;
}

export interface EnvListQuery {
  readonly application: string;
  readonly page: number;
  readonly page_size: number;
}

export interface PullResult {
  readonly created: boolean;
  readonly version: EnvVersion;
}

export interface EnvComparison {
  readonly from: string;
  readonly to: string;
  readonly added: readonly string[];
  readonly removed: readonly string[];
  readonly changed: readonly string[];
}

export interface RevealedEnv {
  readonly content: string;
}

export interface PushResult {
  readonly version: EnvVersion;
}

export type EnvLocation = 'host' | 'container';

export interface EnvPlace {
  readonly env_path: string;
  readonly env_location: EnvLocation;
}

export function envFileName(path: string): string {
  const name = path.slice(path.lastIndexOf('/') + 1);
  return name === '' ? '.env' : name;
}
