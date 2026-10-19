import type { Revisions } from '../../data/redeploy.types';

export interface SavedStepRow {
  readonly position: number;
  readonly label: string;
  readonly details: readonly string[];
  readonly problems: readonly string[];
}

export interface RevisionRow {
  readonly kind: keyof Revisions;
  readonly before: string | null;
  readonly after: string | null;
}
