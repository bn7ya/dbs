export interface WallClock {
  readonly year: number;
  readonly month: number;
  readonly day: number;
  readonly hours: number;
  readonly minutes: number;
}

export interface MomentParts {
  readonly day: Date | null;
  readonly time: Date | null;
}

export type MomentPart = keyof MomentParts;

export interface MomentProblem {
  readonly part: MomentPart;
  readonly code: 'required' | 'invalid_moment';
}
