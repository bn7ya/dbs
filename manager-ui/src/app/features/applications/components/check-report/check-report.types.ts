export type Presence = 'found' | 'missing' | 'notSet' | 'notChecked' | 'running' | 'stopped';

export interface PresenceLook {
  readonly icon: string;
  readonly muted: boolean;
}

export interface ReportRow {
  readonly labelKey: string;
  readonly value: string | null;
  readonly presence: Presence;
}

export interface RootRow {
  readonly path: string;
  readonly presence: Presence;
}

export type Verdict = 'ready' | 'notInstalled' | 'incompatible' | 'unknown';
