import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import {
  Router,
  UrlTree,
  provideRouter,
  type ActivatedRouteSnapshot,
  type GuardResult,
  type RouterStateSnapshot,
} from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { OPERATOR } from '@core/auth/testing/identity.fixtures';
import { errorInterceptor } from '@core/http/error.interceptor';
import { consoleGuard } from './console.guard';

describe('consoleGuard', () => {
  let http: HttpTestingController;

  const enter = (): Promise<GuardResult> =>
    TestBed.runInInjectionContext(
      () =>
        consoleGuard({} as ActivatedRouteSnapshot, { url: '/console' } as RouterStateSnapshot) as Promise<GuardResult>,
    );

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
  });

  it('lets any role that may run commands in', async () => {
    const entering = enter();
    http.expectOne('/api/auth/me/').flush(OPERATOR);

    await expect(entering).resolves.toBe(true);
  });

  it('turns away an account whose role may not', async () => {
    const entering = enter();
    http.expectOne('/api/auth/me/').flush({ ...OPERATOR, capabilities: [] });

    const result = await entering;
    expect(result).toBeInstanceOf(UrlTree);
    expect(TestBed.inject(Router).serializeUrl(result as UrlTree)).toBe('/forbidden');
  });

  it('sends a signed-out visitor to sign in, with the way back', async () => {
    const entering = enter();
    http.expectOne('/api/auth/me/').flush(null, { status: 403, statusText: 'Forbidden' });
    (await vi.waitFor(() => http.expectOne('/api/setup/'))).flush({ needed: false });

    const result = await entering;
    expect(TestBed.inject(Router).serializeUrl(result as UrlTree)).toBe('/sign-in?next=%2Fconsole');
  });
});
