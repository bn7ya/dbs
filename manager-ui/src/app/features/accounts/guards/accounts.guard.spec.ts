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

import { MASTER } from '@core/auth/testing/identity.fixtures';
import { errorInterceptor } from '@core/http/error.interceptor';
import { accountsGuard } from './accounts.guard';

describe('accountsGuard', () => {
  let http: HttpTestingController;

  const enter = (): Promise<GuardResult> =>
    TestBed.runInInjectionContext(
      () =>
        accountsGuard({} as ActivatedRouteSnapshot, { url: '/accounts' } as RouterStateSnapshot) as Promise<GuardResult>,
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

  it('lets the master account in', async () => {
    const entering = enter();
    http.expectOne('/api/auth/me/').flush(MASTER);

    await expect(entering).resolves.toBe(true);
  });

  it('turns any other role away', async () => {
    const entering = enter();
    http.expectOne('/api/auth/me/').flush({ ...MASTER, role: 'admin', capabilities: ['servers.manage'] });

    const result = await entering;
    expect(result).toBeInstanceOf(UrlTree);
    expect(TestBed.inject(Router).serializeUrl(result as UrlTree)).toBe('/forbidden');
  });
});
