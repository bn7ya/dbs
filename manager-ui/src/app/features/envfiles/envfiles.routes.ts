import type { Routes } from '@angular/router';

import { provideTranslations } from '@core/i18n/provide-translations';
import { envfilesGuard } from './guards/envfiles.guard';
import ar from './i18n/ar.json';
import en from './i18n/en.json';
import { EnvfilesStore } from './state/envfiles.store';

export const routes: Routes = [
  {
    path: '',
    canActivate: [envfilesGuard],
    providers: [EnvfilesStore, provideTranslations(en, ar)],
    loadComponent: () => import('./pages/envfiles/envfiles').then((m) => m.EnvfilesPage),
  },
];
