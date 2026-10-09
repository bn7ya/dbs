import type { Routes } from '@angular/router';

import { provideTranslations } from '@core/i18n/provide-translations';
import { filesGuard } from './guards/files.guard';
import ar from './i18n/ar.json';
import en from './i18n/en.json';
import { FilesStore } from './state/files.store';

export const routes: Routes = [
  {
    path: '',
    canActivate: [filesGuard],
    providers: [FilesStore, provideTranslations(en, ar)],
    loadComponent: () => import('./pages/files/files').then((m) => m.FilesPage),
  },
];
