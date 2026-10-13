import type { Routes } from '@angular/router';

import { provideTranslations } from '@core/i18n/provide-translations';
import { accountsGuard } from './guards/accounts.guard';
import ar from './i18n/ar.json';
import en from './i18n/en.json';
import { AccountsStore } from './state/accounts.store';

export const routes: Routes = [
  {
    path: '',
    canActivate: [accountsGuard],
    providers: [AccountsStore, provideTranslations(en, ar)],
    loadComponent: () => import('./pages/accounts/accounts').then((m) => m.AccountsPage),
  },
];
