import type { Runtime } from '../../data/servers.types';

export interface RuntimeSettings {
  readonly runtime: Runtime;
  readonly compose_service: string;
  readonly compose_files: readonly string[];
}

export interface RuntimeOption {
  readonly value: Runtime;
  readonly labelKey: string;
}

export type ComposeField = 'compose_service' | 'compose_files' | 'project_dir';

export interface ComposeTarget extends RuntimeSettings {
  readonly project_dir: string;
}
