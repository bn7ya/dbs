import type { Routes } from '@angular/router';

import { provideTranslations } from '@core/i18n/provide-translations';
import { terminalGuard } from './guards/terminal.guard';
import ar from './i18n/ar.json';
import en from './i18n/en.json';
import { TerminalStore } from './state/terminal.store';

export const routes: Routes = [
  {
    path: '',
    canActivate: [terminalGuard],
    providers: [TerminalStore, provideTranslations(en, ar)],
    loadComponent: () => import('./pages/terminal/terminal').then((m) => m.TerminalPage),
  },
];
