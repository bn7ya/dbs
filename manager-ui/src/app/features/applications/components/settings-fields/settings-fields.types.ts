import type { ApplicationSettings, EnvLocation } from '../../data/applications.types';

export type ApplicationDraft = ApplicationSettings;

export type DraftField = keyof ApplicationDraft;

export type DraftErrors = Readonly<Partial<Record<DraftField, string>>>;

export interface LocationOption {
  readonly value: EnvLocation;
  readonly labelKey: string;
}
