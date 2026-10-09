export interface RedeployServer {
  readonly id: string;
  readonly name: string;
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

export interface RedeployRequest {
  readonly source_server: string;
  readonly target_server: string;
  readonly backup: string;
  readonly env_version: string | null;
  readonly archives: readonly string[];
  readonly migrate: boolean;
  readonly flush: boolean;
  readonly rehearsal: boolean;
  readonly password: string;
  readonly confirm_name: string;
}

export type RedeployStepCode = 'check' | 'env' | 'migrate' | 'restore' | 'archives' | 'final_check';

export type RedeployStepStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped';

export interface RedeployStep {
  readonly step: RedeployStepCode;
  readonly status: RedeployStepStatus;
}

export const REDEPLOY_LIST_SIZE = 100;

export function stepsOf(detail: Readonly<Record<string, unknown>>): readonly RedeployStep[] {
  const steps = detail['steps'];
  if (!Array.isArray(steps)) {
    return [];
  }
  return steps.filter(
    (each: unknown): each is RedeployStep =>
      typeof each === 'object' &&
      each !== null &&
      typeof (each as RedeployStep).step === 'string' &&
      typeof (each as RedeployStep).status === 'string',
  );
}
