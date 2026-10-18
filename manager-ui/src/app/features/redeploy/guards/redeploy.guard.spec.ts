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

import type { Identity } from '@core/auth/data/auth.types';
import { MASTER, OPERATOR } from '@core/auth/testing/identity.fixtures';
import { errorInterceptor } from '@core/http/error.interceptor';
import { redeployGuard } from './redeploy.guard';

const VIEWER: Identity = { ...OPERATOR, id: 3, username: 'lina', role: 'viewer', capabilities: ['console.run'] };

describe('redeployGuard', () => {
  let http: HttpTestingController;

  const enter = (url: string): Promise<GuardResult> =>
    TestBed.runInInjectionContext(
      () =>
        redeployGuard({} as ActivatedRouteSnapshot, { url } as RouterStateSnapshot) as Promise<GuardResult>,
    );

  const serialized = (result: GuardResult): string => TestBed.inject(Router).serializeUrl(result as UrlTree);

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

  it('lets in a role that may rehearse, an operator as well as the master', async () => {
    const entering = enter('/applications/abc/deploy');
    http.expectOne('/api/auth/me/').flush(OPERATOR);
    await expect(entering).resolves.toBe(true);

    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(withInterceptors([errorInterceptor])), provideHttpClientTesting(), provideRouter([])],
    });
    http = TestBed.inject(HttpTestingController);
    const again = enter('/applications/abc/deploy');
    http.expectOne('/api/auth/me/').flush(MASTER);
    await expect(again).resolves.toBe(true);
  });

  it('sends a role that may not even rehearse to the forbidden page', async () => {
    const entering = enter('/applications/abc/deploy');
    http.expectOne('/api/auth/me/').flush(VIEWER);

    const result = await entering;
    expect(result).toBeInstanceOf(UrlTree);
    expect(serialized(result)).toBe('/forbidden');
  });

  it('sends a signed-out visitor to sign in, with the way back to the deploy page', async () => {
    const entering = enter('/applications/abc/deploy');
    http.expectOne('/api/auth/me/').flush(null, { status: 403, statusText: 'Forbidden' });
    (await vi.waitFor(() => http.expectOne('/api/setup/'))).flush({ needed: false });

    const result = await entering;
    expect(result).toBeInstanceOf(UrlTree);
    expect(serialized(result)).toBe('/sign-in?next=%2Fapplications%2Fabc%2Fdeploy');
  });
});
