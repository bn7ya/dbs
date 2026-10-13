import { HttpBackend, HttpClient, type HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { map, switchMap, type Observable } from 'rxjs';

import { CsrfToken } from './csrf-token';

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS', 'TRACE']);
const COOKIE_NAME = 'csrftoken';
const HEADER_NAME = 'X-CSRFToken';
const TOKEN_URL = '/api/auth/csrf/';

export const csrfInterceptor: HttpInterceptorFn = (request, next) => {
  if (SAFE_METHODS.has(request.method)) {
    return next(request);
  }

  const held = inject(CsrfToken);
  const token = readCookie(COOKIE_NAME) ?? held.value();
  if (token) {
    return next(request.clone({ setHeaders: { [HEADER_NAME]: token } }));
  }

  // Behind a TLS proxy the cookie is HttpOnly, so the token is asked for once and kept in memory.
  return fetchToken(new HttpClient(inject(HttpBackend)), held).pipe(
    switchMap((fetched) => next(request.clone({ setHeaders: { [HEADER_NAME]: fetched } }))),
  );
};

function fetchToken(http: HttpClient, held: CsrfToken): Observable<string> {
  return http.get<{ csrf_token: string }>(TOKEN_URL).pipe(
    map((answer) => {
      held.hold(answer.csrf_token);
      return answer.csrf_token;
    }),
  );
}

function readCookie(name: string): string | null {
  const prefix = `${name}=`;
  for (const part of document.cookie.split('; ')) {
    if (part.startsWith(prefix)) {
      return decodeURIComponent(part.slice(prefix.length));
    }
  }
  return null;
}
