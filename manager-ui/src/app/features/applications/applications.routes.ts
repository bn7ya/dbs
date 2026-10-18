import type { Routes } from '@angular/router';

import { capabilityGuard } from '@core/auth/guards/auth.guard';
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
    children: [
      {
        path: '',
        canActivate: [applicationsGuard],
        loadComponent: () => import('./pages/applications/applications').then((m) => m.ApplicationsPage),
      },
      {
        path: ':applicationId',
        canActivate: [applicationsGuard],
        loadComponent: () => import('./pages/application/application').then((m) => m.ApplicationPage),
        children: [
          {
            path: '',
            canActivate: [applicationsGuard],
            loadComponent: () =>
              import('./pages/application-overview/application-overview').then((m) => m.ApplicationOverviewPage),
          },
          {
            path: 'backups',
            canActivate: [applicationsGuard],
            loadChildren: () => import('@features/backups/backups.routes').then((m) => m.routes),
          },
          {
            path: 'schedule',
            canActivate: [applicationsGuard],
            loadChildren: () => import('@features/backups/plans.routes').then((m) => m.routes),
          },
          {
            path: 'files',
            canActivate: [applicationsGuard],
            loadChildren: () => import('@features/files/files.routes').then((m) => m.routes),
          },
          {
            path: 'environment',
            canActivate: [applicationsGuard],
            loadChildren: () => import('@features/envfiles/envfiles.routes').then((m) => m.routes),
          },
          {
            path: 'deploy',
            canActivate: [applicationsGuard],
            loadChildren: () => import('@features/redeploy/redeploy.routes').then((m) => m.routes),
          },
          {
            path: 'terminal',
            canActivate: [capabilityGuard('shell.open')],
            data: { mode: 'application' },
            loadChildren: () => import('@features/terminal/terminal.routes').then((m) => m.routes),
          },
          {
            path: 'activity',
            canActivate: [applicationsGuard],
            loadChildren: () => import('@features/activity/activity.routes').then((m) => m.routes),
          },
        ],
      },
    ],
  },
];
