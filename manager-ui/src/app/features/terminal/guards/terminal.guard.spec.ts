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
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { MASTER, OPERATOR } from '@core/auth/testing/identity.fixtures';
import { errorInterceptor } from '@core/http/error.interceptor';
import { terminalGuard } from './terminal.guard';

describe('terminalGuard', () => {
  let http: HttpTestingController;

  const enter = (): Promise<GuardResult> =>
    TestBed.runInInjectionContext(
      () =>
        terminalGuard(
          {} as ActivatedRouteSnapshot,
          { url: '/servers/one/terminal' } as RouterStateSnapshot,
        ) as Promise<GuardResult>,
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

  it('lets a role that may open a shell in', async () => {
    const entering = enter();
    http.expectOne('/api/auth/me/').flush({ ...MASTER, role: 'admin' });

    await expect(entering).resolves.toBe(true);
  });

  it('turns a role without the shell away', async () => {
    const entering = enter();
    http.expectOne('/api/auth/me/').flush(OPERATOR);

    const result = await entering;
    expect(result).toBeInstanceOf(UrlTree);
    expect(TestBed.inject(Router).serializeUrl(result as UrlTree)).toBe('/forbidden');
  });
});
