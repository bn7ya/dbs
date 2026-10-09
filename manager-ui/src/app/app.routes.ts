import type { Routes } from '@angular/router';

import { authGuard, guestGuard } from '@core/auth/guards/auth.guard';
import { provideTranslations } from '@core/i18n/provide-translations';
import { setupGuard } from '@core/setup/guards/setup.guard';
import setupAr from '@core/setup/i18n/ar.json';
import setupEn from '@core/setup/i18n/en.json';

export const routes: Routes = [
  {
    path: 'setup',
    canActivate: [setupGuard],
    providers: [provideTranslations(setupEn, setupAr)],
    loadComponent: () => import('@core/setup/pages/setup/setup').then((m) => m.SetupPage),
  },
  {
    path: 'sign-in',
    canActivate: [guestGuard],
    loadComponent: () => import('@core/auth/pages/sign-in/sign-in').then((m) => m.SignInPage),
  },
  {
    path: 'forbidden',
    canActivate: [authGuard],
    data: { titleKey: 'errors.forbidden', bodyKey: 'errors.forbiddenBody' },
    loadComponent: () => import('@shared/status-page/status-page').then((m) => m.StatusPage),
  },
  {
    path: '',
    canActivate: [authGuard],
    loadComponent: () => import('@core/layout/app-layout/app-layout').then((m) => m.AppLayout),
    children: [
      {
        path: '',
        pathMatch: 'full',
        loadChildren: () => import('@features/dashboard/dashboard.routes').then((m) => m.routes),
      },
      {
        path: 'servers',
        loadChildren: () => import('@features/servers/servers.routes').then((m) => m.routes),
      },
      {
        path: 'activity',
        loadChildren: () => import('@features/activity/activity.routes').then((m) => m.routes),
      },
      {
        // Inside the layout, so a signed-in reader who follows a dead link keeps the navigation.
        path: '**',
        canActivate: [authGuard],
        data: { titleKey: 'errors.notFound', bodyKey: 'errors.notFoundBody' },
        loadComponent: () => import('@shared/status-page/status-page').then((m) => m.StatusPage),
      },
    ],
  },
];
