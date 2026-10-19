import type { Routes } from '@angular/router';

import { provideTranslations } from '@core/i18n/provide-translations';
import { consoleGuard } from './guards/console.guard';
import ar from './i18n/ar.json';
import en from './i18n/en.json';
import { ConsoleStore } from './state/console.store';

export const routes: Routes = [
  {
    path: '',
    canActivate: [consoleGuard],
    providers: [ConsoleStore, provideTranslations(en, ar)],
    loadComponent: () => import('./pages/console/console').then((m) => m.ConsolePage),
  },
];
