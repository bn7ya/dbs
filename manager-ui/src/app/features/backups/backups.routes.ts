import type { Routes } from '@angular/router';

import { provideTranslations } from '@core/i18n/provide-translations';
import { backupsGuard } from './guards/backups.guard';
import ar from './i18n/ar.json';
import en from './i18n/en.json';
import { BackupsStore } from './state/backups.store';

export const routes: Routes = [
  {
    path: '',
    canActivate: [backupsGuard],
    providers: [BackupsStore, provideTranslations(en, ar)],
    loadComponent: () => import('./pages/backups/backups').then((m) => m.BackupsPage),
  },
];
