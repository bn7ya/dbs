import type { DeploymentQuestion } from '../../data/applications.types';

export interface SettingRow {
  readonly labelKey: string;
  readonly code?: string;
  readonly textKey?: string;
}

export interface DeploymentRow {
  readonly question: DeploymentQuestion;
  readonly saidKey: string;
  readonly foundKey: string;
  readonly differs: boolean;
}
