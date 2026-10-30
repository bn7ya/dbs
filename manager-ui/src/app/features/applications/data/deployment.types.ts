import type { ApplicationEngine, ApplicationKind, DeploymentQuestion } from './applications.types';

export interface QuestionDefinition {
  readonly key: DeploymentQuestion;
  readonly options: readonly string[];
}

export interface NextStep {
  readonly key: string;
  readonly values: Readonly<Record<string, string>>;
  readonly command: string;
}

export interface StepPlace {
  readonly kind: ApplicationKind;
  readonly engine: ApplicationEngine;
  readonly compose_service: string;
  readonly container_name: string;
  readonly python_path: string;
  readonly remote_backup_dir: string;
  readonly env_path?: string;
}
