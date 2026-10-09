import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import {
  Router,
  UrlTree,
  convertToParamMap,
  provideRouter,
  type ActivatedRouteSnapshot,
  type CanActivateFn,
  type GuardResult,
  type RouterStateSnapshot,
} from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { authGuard, guestGuard } from '@core/auth/guards/auth.guard';
import { errorInterceptor } from '@core/http/error.interceptor';
import { setupGuard } from './setup.guard';

describe('first-run guards', () => {
  let http: HttpTestingController;

  const enter = (guard: CanActivateFn, url: string, query: Record<string, string> = {}): Promise<GuardResult> =>
    TestBed.runInInjectionContext(
      () =>
        guard(
          { queryParamMap: convertToParamMap(query) } as ActivatedRouteSnapshot,
          { url } as RouterStateSnapshot,
        ) as Promise<GuardResult>,
    );

  const serialized = (result: GuardResult): string => TestBed.inject(Router).serializeUrl(result as UrlTree);

  const signedOut = async (): Promise<void> => {
    http.expectOne('/api/auth/me/').flush(null, { status: 403, statusText: 'Forbidden' });
    await vi.waitFor(() => http.expectOne('/api/setup/')).then((request) => request.flush({ needed: true }));
  };

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

  it('opens the setup page while no account exists', async () => {
    const entering = enter(setupGuard, '/setup');
    http.expectOne('/api/setup/').flush({ needed: true });

    await expect(entering).resolves.toBe(true);
  });

  it('sends a visitor away from the setup page once an account exists', async () => {
    const entering = enter(setupGuard, '/setup');
    http.expectOne('/api/setup/').flush({ needed: false });

    const result = await entering;
    expect(result).toBeInstanceOf(UrlTree);
    expect(serialized(result)).toBe('/');
  });

  it('sends a signed-out visitor to setup, keeping the key from the link', async () => {
    const entering = enter(authGuard, '/?token=k3y', { token: 'k3y' });
    await signedOut();

    expect(serialized(await entering)).toBe('/setup?token=k3y');
  });

  it('sends the sign-in page to setup while no account exists', async () => {
    const entering = enter(guestGuard, '/sign-in');
    await signedOut();

    expect(serialized(await entering)).toBe('/setup');
  });
});
