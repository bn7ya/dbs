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

import type { Identity } from '@core/auth/data/auth.types';
import { errorInterceptor } from '@core/http/error.interceptor';
import { serversGuard } from './servers.guard';

const IDENTITY: Identity = {
  id: 1,
  username: 'sara',
  email: 'sara@example.com',
  first_name: 'Sara',
  last_name: 'Hassan',
  is_staff: false,
  is_superuser: false,
  groups: [],
  permissions: [],
};

describe('serversGuard', () => {
  let http: HttpTestingController;

  const enter = (url: string): Promise<GuardResult> =>
    TestBed.runInInjectionContext(
      () =>
        serversGuard({} as ActivatedRouteSnapshot, { url } as RouterStateSnapshot) as Promise<GuardResult>,
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

  it('lets a signed-in user in', async () => {
    const entering = enter('/servers');
    http.expectOne('/api/auth/me/').flush(IDENTITY);

    await expect(entering).resolves.toBe(true);
  });

  it('sends a signed-out visitor to sign in, with the way back', async () => {
    const entering = enter('/servers');
    http.expectOne('/api/auth/me/').flush(null, { status: 403, statusText: 'Forbidden' });

    const result = await entering;
    expect(result).toBeInstanceOf(UrlTree);
    expect(TestBed.inject(Router).serializeUrl(result as UrlTree)).toBe('/sign-in?next=%2Fservers');
  });
});
