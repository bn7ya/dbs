import type { Routes } from '@angular/router';

import { provideTranslations } from '@core/i18n/provide-translations';
import { aboutGuard } from './guards/about.guard';
import ar from './i18n/ar.json';
import en from './i18n/en.json';
import { AboutStore } from './state/about.store';

export const routes: Routes = [
  {
    path: '',
    canActivate: [aboutGuard],
    providers: [AboutStore, provideTranslations(en, ar)],
    loadComponent: () => import('./pages/about/about').then((m) => m.AboutPage),
  },
];
