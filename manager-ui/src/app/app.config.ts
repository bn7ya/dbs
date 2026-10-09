import { APP_BASE_HREF } from '@angular/common';
import { provideHttpClient, withInterceptors, withXhr } from '@angular/common/http';
import {
  provideBrowserGlobalErrorListeners,
  provideZonelessChangeDetection,
  type ApplicationConfig,
} from '@angular/core';
import { provideRouter, withComponentInputBinding, withViewTransitions } from '@angular/router';
import { ConfirmationService, MessageService } from 'primeng/api';
import { providePrimeNG } from 'primeng/config';

import { csrfInterceptor } from '@core/http/csrf.interceptor';
import { errorInterceptor } from '@core/http/error.interceptor';
import { AppPreset } from './app.preset';
import { PRIMEUI_LICENSE } from './primeui-license';
import { routes } from './app.routes';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),

    provideZonelessChangeDetection(),

    provideRouter(routes, withComponentInputBinding(), withViewTransitions()),

    { provide: APP_BASE_HREF, useValue: '/' },

    // XHR, not fetch: a backup upload shows the bytes sent, and only XHR reports upload progress.
    provideHttpClient(withXhr(), withInterceptors([csrfInterceptor, errorInterceptor])),

    providePrimeNG({
      license: PRIMEUI_LICENSE,
      theme: {
        preset: AppPreset,
        options: { cssLayer: { name: 'primeng', order: 'reset, base, primeng, app' } },
      },
    }),

    MessageService,
    ConfirmationService,
  ],
};
