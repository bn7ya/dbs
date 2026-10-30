import type { Routes } from '@angular/router';

import { capabilityGuard } from '@core/auth/guards/auth.guard';
import { provideTranslations } from '@core/i18n/provide-translations';
import { serversGuard } from './guards/servers.guard';
import ar from './i18n/ar.json';
import en from './i18n/en.json';
import { ServerWizardStore } from './state/server-wizard.store';
import { ServersStore } from './state/servers.store';

export const routes: Routes = [
  {
    path: '',
    canActivate: [serversGuard],
    providers: [ServersStore, provideTranslations(en, ar)],
    children: [
      {
        path: '',
        canActivate: [serversGuard],
        loadComponent: () => import('./pages/servers/servers').then((m) => m.ServersPage),
      },
      {
        path: 'new',
        canActivate: [capabilityGuard('servers.manage')],
        providers: [ServerWizardStore],
        loadComponent: () => import('./pages/server-wizard/server-wizard').then((m) => m.ServerWizardPage),
      },
      {
        path: ':serverId/applications/new',
        canActivate: [capabilityGuard('applications.manage')],
        loadChildren: () => import('@features/applications/application-wizard.routes').then((m) => m.routes),
      },
      {
        path: ':serverId/move',
        canActivate: [capabilityGuard('relocation.rehearse')],
        loadChildren: () => import('@features/relocation/relocation.routes').then((m) => m.routes),
      },
      {
        path: ':serverId',
        canActivate: [serversGuard],
        loadComponent: () => import('./pages/server/server').then((m) => m.ServerPage),
        children: [
          {
            path: '',
            canActivate: [serversGuard],
            loadComponent: () =>
              import('./pages/server-overview/server-overview').then((m) => m.ServerOverviewPage),
          },
          {
            path: 'applications',
            canActivate: [serversGuard],
            loadChildren: () => import('@features/applications/server-applications.routes').then((m) => m.routes),
          },
          {
            path: 'terminal',
            canActivate: [capabilityGuard('shell.open')],
            data: { mode: 'server' },
            loadChildren: () => import('@features/terminal/terminal.routes').then((m) => m.routes),
          },
          {
            path: 'activity',
            canActivate: [serversGuard],
            loadChildren: () => import('@features/activity/activity.routes').then((m) => m.routes),
          },
        ],
      },
    ],
  },
];
