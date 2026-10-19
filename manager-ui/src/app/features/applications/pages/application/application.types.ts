import type { Capability } from '@core/auth/data/auth.types';

export interface ApplicationTab {
  readonly path: string;
  readonly labelKey: string;
  readonly capability?: Capability;
}
