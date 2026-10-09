export interface Section {
  readonly path: string;
  readonly labelKey: string;
  readonly icon: string;
}

export const SECTIONS: readonly Section[] = [
  { path: '', labelKey: 'nav.dashboard', icon: 'fa-solid fa-gauge' },
  { path: 'servers', labelKey: 'nav.servers', icon: 'fa-solid fa-server' },
  { path: 'activity', labelKey: 'nav.activity', icon: 'fa-solid fa-heart-pulse' },
];
