import type { StepProblem } from '../../data/deploy-catalogue.types';
import type { DeployStepKind } from '../../data/redeploy.types';

export interface DraftStep {
  readonly key: number;
  readonly kind: DeployStepKind;
  readonly remote: string;
  readonly branch: string;
  readonly services: readonly string[];
  readonly pull: boolean;
  readonly unit: string;
  readonly requirements: string;
  readonly timeout: number | null;
}

export type DraftField = 'remote' | 'branch' | 'services' | 'unit' | 'requirements' | 'timeout';

export type DraftProblems = Readonly<Record<DraftField, StepProblem | null>>;

export type DraftPatch = Partial<Omit<DraftStep, 'key' | 'kind'>>;
