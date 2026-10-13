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
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import type { Identity } from '../data/auth.types';
import { AuthStore } from '../state/auth.store';
import { MASTER, OPERATOR } from '../testing/identity.fixtures';
import { authGuard, capabilityGuard, passwordGuard, stepGuard } from './auth.guard';

describe('auth guards', () => {
  let http: HttpTestingController;

  const enter = (guard: CanActivateFn, url: string, query: Record<string, string> = {}): Promise<GuardResult> =>
    TestBed.runInInjectionContext(async () =>
      guard({ queryParamMap: convertToParamMap(query) } as ActivatedRouteSnapshot, { url } as RouterStateSnapshot),
    ) as Promise<GuardResult>;

  const target = (result: GuardResult): string => {
    expect(result).toBeInstanceOf(UrlTree);
    return TestBed.inject(Router).serializeUrl(result as UrlTree);
  };

  const signedInAs = (identity: Identity): void => {
    http.expectOne('/api/auth/me/').flush(identity);
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

  it('sends an account whose password must change to the change-password page', async () => {
    const entering = enter(authGuard, '/servers');
    signedInAs({ ...MASTER, password_change_required: true });

    expect(target(await entering)).toBe('/password');
  });

  it('opens the change-password page only while a change is required', async () => {
    const required = enter(passwordGuard, '/password');
    signedInAs({ ...MASTER, password_change_required: true });
    await expect(required).resolves.toBe(true);

    const restoring = TestBed.inject(AuthStore).restore();
    signedInAs(MASTER);
    await restoring;
    expect(target(await enter(passwordGuard, '/password'))).toBe('/account');
  });

  it('opens a page that needs a capability only for a role that has it', async () => {
    const operator = enter(capabilityGuard('accounts.manage'), '/accounts');
    signedInAs(OPERATOR);
    expect(target(await operator)).toBe('/forbidden');

    const restoring = TestBed.inject(AuthStore).restore();
    signedInAs(MASTER);
    await restoring;
    await expect(enter(capabilityGuard('accounts.manage'), '/accounts')).resolves.toBe(true);
  });

  it('opens a sign-in step only while that step is waiting', async () => {
    const auth = TestBed.inject(AuthStore);

    expect(target(await enter(stepGuard('code'), '/sign-in/code', { next: '/servers' }))).toBe(
      '/sign-in?next=%2Fservers',
    );

    auth.begin('code');
    await expect(enter(stepGuard('code'), '/sign-in/code')).resolves.toBe(true);
    expect(target(await enter(stepGuard('enroll'), '/sign-in/enroll'))).toBe('/sign-in');
  });
});
