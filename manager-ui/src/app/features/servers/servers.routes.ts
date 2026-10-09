import type { Routes } from '@angular/router';

import { provideTranslations } from '@core/i18n/provide-translations';
import { serversGuard } from './guards/servers.guard';
import ar from './i18n/ar.json';
import en from './i18n/en.json';
import { ServersStore } from './state/servers.store';

export const routes: Routes = [
  {
    path: '',
    canActivate: [serversGuard],
    providers: [ServersStore, provideTranslations(en, ar)],
    children: [
      {
        path: '',
        loadComponent: () => import('./pages/servers/servers').then((m) => m.ServersPage),
      },
      {
        path: ':serverId',
        loadComponent: () => import('./pages/server/server').then((m) => m.ServerPage),
        children: [
          {
            path: '',
            loadComponent: () =>
              import('./pages/server-overview/server-overview').then((m) => m.ServerOverviewPage),
          },
          {
            path: 'backups',
            loadChildren: () => import('@features/backups/backups.routes').then((m) => m.routes),
          },
          {
            path: 'files',
            loadChildren: () => import('@features/files/files.routes').then((m) => m.routes),
          },
          {
            path: 'environment',
            loadChildren: () => import('@features/envfiles/envfiles.routes').then((m) => m.routes),
          },
          {
            path: 'activity',
            loadChildren: () => import('@features/activity/activity.routes').then((m) => m.routes),
          },
        ],
      },
    ],
  },
];
