import type { Capability } from '@core/auth/data/auth.types';

export interface ServerTab {
  readonly path: string;
  readonly labelKey: string;
  readonly capability?: Capability;
}
