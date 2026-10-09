import type { Routes } from '@angular/router';

import { authGuard, guestGuard } from '@core/auth/guards/auth.guard';

export const routes: Routes = [
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
        // No guard here: Angular's router rejects `canActivate` alongside `redirectTo` on the same
        // entry (NG04014). The layout's `authGuard` above covers it.
        redirectTo: 'servers',
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
