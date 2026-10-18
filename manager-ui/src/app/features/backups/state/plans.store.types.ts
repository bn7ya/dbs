export interface PlanRun {
  readonly application: string;
  readonly plan: string;
  readonly name: string;
}

export type PlanChange = 'pause' | 'resume';
