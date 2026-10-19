import type { DraftProblems, DraftStep } from './step-drafts.types';

export interface DraftRow {
  readonly draft: DraftStep;
  readonly position: number;
  readonly first: boolean;
  readonly last: boolean;
  readonly services: boolean;
  readonly fields: DraftProblems;
  readonly messages: readonly string[];
}
