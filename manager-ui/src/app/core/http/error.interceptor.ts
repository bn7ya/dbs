import { HttpErrorResponse, type HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';

import { AuthStore } from '@core/auth/state/auth.store';
import { LocaleStore } from '@core/i18n/locale.store';
import type { ApiError, ApiErrorResponse } from './api.types';

// Only these 401/403 codes mean the session is gone; any other is about the request itself.
const SESSION_FAILURES: ReadonlySet<string> = new Set(['not_authenticated', 'authentication_failed']);

export const errorInterceptor: HttpInterceptorFn = (request, next) => {
  const router = inject(Router);
  const locale = inject(LocaleStore);
  const auth = inject(AuthStore);

  return next(request).pipe(
    catchError((response: unknown) => {
      const error = toApiError(response, locale);

      if (response instanceof HttpErrorResponse && isSessionFailure(response, error, request.url)) {
        // Forgotten first: the sign-in page's guard turns a signed-in user away.
        auth.forget();
        void router.navigate(['/sign-in'], {
          queryParams: { next: router.url },
          replaceUrl: true,
        });
      }

      return throwError(() => error);
    }),
  );
};

function isSessionFailure(response: HttpErrorResponse, error: ApiError, url: string): boolean {
  if (response.status !== 401 && response.status !== 403) {
    return false;
  }
  // Under /api/auth/ a refusal means "those credentials were refused", not "your
  // session is gone" — redirecting there would loop.
  return SESSION_FAILURES.has(error.code) && !url.includes('/api/auth/');
}

function toApiError(response: unknown, locale: LocaleStore): ApiError {
  if (!(response instanceof HttpErrorResponse)) {
    return { code: 'unknown', message: locale.translate('errors.generic') };
  }

  if (response.status === 0) {
    return { code: 'network', message: locale.translate('auth.errors.unavailable') };
  }

  const body = response.error as ApiErrorResponse | null;
  if (body?.error?.message) {
    return body.error;
  }

  // A URL Django's resolver rejects outright — a malformed id in a detail route — never reaches
  // DRF, so it arrives as Django's HTML 404 with no envelope. It is still "not found".
  if (response.status === 404) {
    return { code: 'not_found', message: locale.translate('errors.not_found') };
  }

  // A body past the limit of the proxy in front of Django — nginx's `client_max_body_size` — is
  // refused there, as an HTML 413 with no envelope. It is still the upload being too large.
  if (response.status === 413) {
    return { code: 'upload_too_large', message: locale.translate('errors.upload_too_large') };
  }

  return { code: 'unknown', message: locale.translate('errors.generic') };
}
