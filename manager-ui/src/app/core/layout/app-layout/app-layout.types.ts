import type { Capability } from '@core/auth/data/auth.types';

export interface Section {
  readonly path: string;
  readonly labelKey: string;
  readonly icon: string;
  readonly capability?: Capability;
}

export const SECTIONS: readonly Section[] = [
  { path: '', labelKey: 'nav.dashboard', icon: 'fa-solid fa-gauge' },
  { path: 'servers', labelKey: 'nav.servers', icon: 'fa-solid fa-server' },
  { path: 'activity', labelKey: 'nav.activity', icon: 'fa-solid fa-heart-pulse' },
  { path: 'accounts', labelKey: 'nav.accounts', icon: 'fa-solid fa-users', capability: 'accounts.manage' },
];
