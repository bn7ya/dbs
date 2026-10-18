import type { Routes } from '@angular/router';

import { capabilityGuard } from '@core/auth/guards/auth.guard';
import { provideTranslations } from '@core/i18n/provide-translations';
import ar from './i18n/ar.json';
import en from './i18n/en.json';
import { ApplicationWizardStore } from './state/application-wizard.store';

export const routes: Routes = [
  {
    path: '',
    canActivate: [capabilityGuard('applications.manage')],
    providers: [ApplicationWizardStore, provideTranslations(en, ar)],
    loadComponent: () => import('./pages/application-wizard/application-wizard').then((m) => m.ApplicationWizardPage),
  },
];
