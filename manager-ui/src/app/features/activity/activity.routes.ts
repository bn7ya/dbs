import type { Routes } from '@angular/router';

import { provideTranslations } from '@core/i18n/provide-translations';
import { activityGuard } from './guards/activity.guard';
import ar from './i18n/ar.json';
import en from './i18n/en.json';
import { ActivityStore } from './state/activity.store';

export const routes: Routes = [
  {
    path: '',
    canActivate: [activityGuard],
    providers: [ActivityStore, provideTranslations(en, ar)],
    loadComponent: () => import('./pages/activity/activity').then((m) => m.ActivityPage),
  },
];
