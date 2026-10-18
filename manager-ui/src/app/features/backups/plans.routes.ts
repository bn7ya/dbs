import type { Routes } from '@angular/router';

import { provideTranslations } from '@core/i18n/provide-translations';
import { backupsGuard } from './guards/backups.guard';
import ar from './i18n/ar.json';
import en from './i18n/en.json';
import { PlansStore } from './state/plans.store';

export const routes: Routes = [
  {
    path: '',
    canActivate: [backupsGuard],
    providers: [PlansStore, provideTranslations(en, ar)],
    loadComponent: () => import('./pages/plans/plans').then((m) => m.PlansPage),
  },
];
