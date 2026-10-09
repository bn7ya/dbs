import { Directionality } from '@angular/cdk/bidi';
import { APP_BASE_HREF } from '@angular/common';
import { provideHttpClient, withInterceptors, withXhr } from '@angular/common/http';
import {
  provideBrowserGlobalErrorListeners,
  provideZonelessChangeDetection,
  type ApplicationConfig,
} from '@angular/core';
import { MAT_FORM_FIELD_DEFAULT_OPTIONS, type MatFormFieldDefaultOptions } from '@angular/material/form-field';
import { MatPaginatorIntl } from '@angular/material/paginator';
import { provideRouter, withComponentInputBinding, withViewTransitions } from '@angular/router';
import { providePrimeNG } from 'primeng/config';

import { csrfInterceptor } from '@core/http/csrf.interceptor';
import { errorInterceptor } from '@core/http/error.interceptor';
import { AppDirectionality } from '@core/i18n/app-directionality';
import { AppPaginatorIntl } from '@core/i18n/app-paginator-intl';
import { AppPreset } from './app.preset';
import { PRIMEUI_LICENSE } from './primeui-license';
import { routes } from './app.routes';

const FORM_FIELD_DEFAULTS: MatFormFieldDefaultOptions = { appearance: 'outline', subscriptSizing: 'dynamic' };

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),

    provideZonelessChangeDetection(),

    provideRouter(routes, withComponentInputBinding(), withViewTransitions()),

    { provide: APP_BASE_HREF, useValue: '/' },

    // XHR, not fetch: a backup upload shows the bytes sent, and only XHR reports upload progress.
    provideHttpClient(withXhr(), withInterceptors([csrfInterceptor, errorInterceptor])),

    { provide: Directionality, useExisting: AppDirectionality },
    { provide: MatPaginatorIntl, useClass: AppPaginatorIntl },
    { provide: MAT_FORM_FIELD_DEFAULT_OPTIONS, useValue: FORM_FIELD_DEFAULTS },

    providePrimeNG({
      license: PRIMEUI_LICENSE,
      theme: {
        preset: AppPreset,
        options: { cssLayer: { name: 'primeng', order: 'reset, base, primeng, material, app' } },
      },
    }),
  ],
};
