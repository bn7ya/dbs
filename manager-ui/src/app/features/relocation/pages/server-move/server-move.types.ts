import type { MoveApplication } from '../../data/relocation.types';

export type MoveWizardStep = 'target' | 'applications' | 'plan' | 'confirm' | 'progress';

export interface DraftSource {
  readonly applications: readonly MoveApplication[];
  readonly target: string;
}
