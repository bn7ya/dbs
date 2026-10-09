export type Presence = 'found' | 'missing' | 'notSet' | 'notChecked';

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

export interface CheckReportView {
  readonly rows: readonly ReportRow[];
  readonly roots: readonly RootRow[];
}

export interface SettingRow {
  readonly labelKey: string;
  readonly code?: string;
  readonly textKey?: string;
}
