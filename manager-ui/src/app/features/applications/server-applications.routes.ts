import type { Routes } from '@angular/router';

import { provideTranslations } from '@core/i18n/provide-translations';
import { applicationsGuard } from './guards/applications.guard';
import ar from './i18n/ar.json';
import en from './i18n/en.json';
import { ApplicationsStore } from './state/applications.store';

export const routes: Routes = [
  {
    path: '',
    canActivate: [applicationsGuard],
    providers: [ApplicationsStore, provideTranslations(en, ar)],
    loadComponent: () => import('./pages/applications/applications').then((m) => m.ApplicationsPage),
  },
];
