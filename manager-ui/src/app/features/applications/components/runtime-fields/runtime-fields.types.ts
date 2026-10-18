import type { ApplicationEngine, ApplicationKind, ContainerEngine } from '../../data/applications.types';

export interface RuntimeSettings {
  readonly kind: ApplicationKind;
  readonly engine: ApplicationEngine;
  readonly compose_project: string;
  readonly compose_service: string;
  readonly compose_files: readonly string[];
  readonly container_name: string;
}

export interface RuntimeTarget extends RuntimeSettings {
  readonly project_dir: string;
}

export type RuntimeField = keyof RuntimeSettings | 'project_dir';

export type RuntimeErrors = Readonly<Partial<Record<RuntimeField, string>>>;

export interface KindOption {
  readonly value: ApplicationKind;
  readonly labelKey: string;
}

export interface EngineOption {
  readonly value: ContainerEngine;
  readonly labelKey: string;
}
