import type { StepStatus } from '@shared/steps-list/steps-list.types';

export type ApplicationKind = 'host' | 'compose' | 'container';

export type DeployStepKind =
  | 'git_pull'
  | 'compose_pull'
  | 'compose_build'
  | 'compose_up'
  | 'restart'
  | 'systemd_user_restart'
  | 'pip_install'
  | 'migrate'
  | 'collectstatic';

export interface DeployStepOptions {
  readonly remote?: string;
  readonly branch?: string;
  readonly services?: readonly string[];
  readonly pull?: boolean;
  readonly unit?: string;
  readonly requirements?: string;
}

export interface DeployStep {
  readonly kind: DeployStepKind;
  readonly options: DeployStepOptions;
  readonly timeout_minutes: number;
}

export interface RedeployServer {
  readonly id: string;
  readonly name: string;
}

export interface DeployApplication {
  readonly id: string;
  readonly name: string;
  readonly server: RedeployServer;
  readonly kind: ApplicationKind;
  readonly project_dir: string;
  readonly deploy_steps: readonly DeployStep[];
}

export interface RedeployApplication {
  readonly id: string;
  readonly name: string;
  readonly server: RedeployServer;
}

export interface RedeployBackup {
  readonly id: string;
  readonly name: string;
  readonly kind: string;
  readonly size: number;
  readonly created_at: string;
}

export interface RedeployEnvVersion {
  readonly id: string;
  readonly path: string;
  readonly created_at: string;
}

export interface DeployStepsRequest {
  readonly steps: readonly DeployStep[];
  readonly account_password: string;
}

export interface RunRequest {
  readonly rehearsal: boolean;
  readonly password: string;
  readonly confirm_name: string;
}

export interface MoveRequest extends RunRequest {
  readonly source_application: string;
  readonly target_application: string;
  readonly backup: string | null;
  readonly env_version: string | null;
  readonly flush: boolean;
}

export type JobDetail = Readonly<Record<string, unknown>>;

export interface JobStep {
  readonly step: string;
  readonly status: StepStatus;
  readonly index?: number;
}

export interface Revisions {
  readonly git_head?: string;
  readonly image?: string;
}

export interface MoveOutcome {
  readonly target: string | null;
  readonly revertable: boolean;
  readonly usedChosenBackup: boolean;
  readonly sourceSilent: boolean;
}

export interface DeployOutcome {
  readonly revertable: boolean;
  readonly before: Revisions;
  readonly after: Revisions;
}
