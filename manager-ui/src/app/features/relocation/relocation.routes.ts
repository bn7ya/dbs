import type { Routes } from '@angular/router';

import { provideTranslations } from '@core/i18n/provide-translations';
import { relocationGuard } from './guards/relocation.guard';
import ar from './i18n/ar.json';
import en from './i18n/en.json';
import { ServerMoveStore } from './state/server-move.store';

export const routes: Routes = [
  {
    path: '',
    canActivate: [relocationGuard],
    providers: [ServerMoveStore, provideTranslations(en, ar)],
    loadComponent: () => import('./pages/server-move/server-move').then((m) => m.ServerMovePage),
  },
];
