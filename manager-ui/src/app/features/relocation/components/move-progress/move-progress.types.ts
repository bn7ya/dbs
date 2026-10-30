import type { ListedStep } from '@shared/steps-list/steps-list.types';

export interface ListedPhase {
  readonly key: string;
  readonly title: string;
  readonly steps: readonly ListedStep[];
}
