import type { Routes } from '@angular/router';

import { provideTranslations } from '@core/i18n/provide-translations';
import { dashboardGuard } from './guards/dashboard.guard';
import ar from './i18n/ar.json';
import en from './i18n/en.json';
import { DashboardStore } from './state/dashboard.store';

export const routes: Routes = [
  {
    path: '',
    canActivate: [dashboardGuard],
    providers: [DashboardStore, provideTranslations(en, ar)],
    loadComponent: () => import('./pages/dashboard/dashboard').then((m) => m.DashboardPage),
  },
];
