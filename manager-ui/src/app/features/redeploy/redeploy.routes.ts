import type { Routes } from '@angular/router';

import { provideTranslations } from '@core/i18n/provide-translations';
import { redeployGuard } from './guards/redeploy.guard';
import ar from './i18n/ar.json';
import en from './i18n/en.json';
import { RedeployStore } from './state/redeploy.store';

export const routes: Routes = [
  {
    path: '',
    canActivate: [redeployGuard],
    providers: [RedeployStore, provideTranslations(en, ar)],
    loadComponent: () => import('./pages/redeploy/redeploy').then((m) => m.RedeployPage),
  },
];
