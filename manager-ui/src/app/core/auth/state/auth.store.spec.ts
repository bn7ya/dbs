import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { CsrfToken } from '@core/http/csrf-token';
import { errorInterceptor } from '@core/http/error.interceptor';
import type { Identity } from '../data/auth.types';
import { MASTER_ACCOUNT, OPERATOR } from '../testing/identity.fixtures';
import { AuthStore } from './auth.store';

const IDENTITY: Identity = {
  id: 1,
  username: 'sara',
  email: 'sara@example.com',
  first_name: 'Sara',
  last_name: 'Hassan',
  is_staff: false,
  is_superuser: false,
  groups: ['members'],
  permissions: ['orders.add_order'],
  ...MASTER_ACCOUNT,
};

const settle = (): Promise<void> => new Promise<void>((resolve) => queueMicrotask(resolve));

describe('AuthStore', () => {
  let store: AuthStore;
  let http: HttpTestingController;

  const restoreAs = async (identity: Identity): Promise<void> => {
    const restoring = store.restore();
    http.expectOne('/api/auth/me/').flush(identity);
    await restoring;
  };

  const passwordStep = async (step: 'code' | 'enroll'): Promise<void> => {
    const signingIn = store.signIn({ username: 'sara', password: 'secret' });
    http.expectOne('/api/auth/csrf/').flush({ csrf_token: 'token' });
    await settle();
    http.expectOne('/api/auth/login/').flush({ step });
    await signingIn;
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    store = TestBed.inject(AuthStore);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
  });

  it('starts unresolved, so guards do not act before /me/ answers', () => {
    expect(store.resolved()).toBe(false);
    expect(store.isAuthenticated()).toBe(false);
  });

  it('holds the identity after restoring a session', async () => {
    await restoreAs(IDENTITY);

    expect(store.resolved()).toBe(true);
    expect(store.isAuthenticated()).toBe(true);
    expect(store.groups()).toEqual(['members']);
    expect(store.role()).toBe('master');
  });

  it('treats a 403 from /me/ as "signed out", not as an error', async () => {
    const restoring = store.restore();
    http.expectOne('/api/auth/me/').flush(null, { status: 403, statusText: 'Forbidden' });
    await restoring;

    expect(store.resolved()).toBe(true);
    expect(store.isAuthenticated()).toBe(false);
    expect(store.error()).toBeNull();
  });

  it('primes CSRF, posts the password and waits for the second step', async () => {
    const signingIn = store.signIn({ username: 'sara', password: 'secret' });

    http.expectOne('/api/auth/csrf/').flush({ csrf_token: 'token' });
    await settle();
    expect(TestBed.inject(CsrfToken).value()).toBe('token');

    const login = http.expectOne('/api/auth/login/');
    expect(login.request.method).toBe('POST');
    login.flush({ step: 'code' });

    await expect(signingIn).resolves.toBe('code');
    expect(store.step()).toBe('code');
    expect(store.isAuthenticated()).toBe(false);
    expect(store.busy()).toBe(false);
  });

  it('keeps the failure when the password is refused', async () => {
    const signingIn = store.signIn({ username: 'sara', password: 'wrong' });

    http.expectOne('/api/auth/csrf/').flush({ csrf_token: 'token' });
    await settle();

    http.expectOne('/api/auth/login/').flush(
      { error: { code: 'authentication_failed', message: "That username and password don't match an account." } },
      { status: 403, statusText: 'Forbidden' },
    );

    await expect(signingIn).resolves.toBeNull();
    expect(store.error()?.code).toBe('authentication_failed');
    expect(store.step()).toBeNull();
  });

  it('signs in with the code and forgets the token the sign-in rotated', async () => {
    await passwordStep('code');

    const verifying = store.secondFactor({ code: '123456' });
    const request = http.expectOne('/api/auth/two-factor/');
    expect(request.request.body).toEqual({ code: '123456' });
    request.flush(IDENTITY);

    await expect(verifying).resolves.toBe(true);
    expect(store.isAuthenticated()).toBe(true);
    expect(store.step()).toBeNull();
    expect(TestBed.inject(CsrfToken).value()).toBeNull();
  });

  it('keeps the step when a code is refused and drops it when the sign-in expired', async () => {
    await passwordStep('code');

    const refused = store.secondFactor({ code: '000000' });
    http
      .expectOne('/api/auth/two-factor/')
      .flush({ error: { code: 'invalid_code', message: 'No' } }, { status: 400, statusText: 'Bad Request' });
    await expect(refused).resolves.toBe(false);
    expect(store.step()).toBe('code');

    const expired = store.secondFactor({ recovery_code: 'abcde-23456' });
    http
      .expectOne('/api/auth/two-factor/')
      .flush({ error: { code: 'sign_in_expired', message: 'Late' } }, { status: 403, statusText: 'Forbidden' });
    await expect(expired).resolves.toBe(false);
    expect(store.step()).toBeNull();
  });

  it('enrolls, signs in and keeps the recovery codes until they are dismissed', async () => {
    await passwordStep('enroll');

    const starting = store.startEnrollment();
    http.expectOne('/api/auth/two-factor/enrollment/').flush({
      secret: 'JBSWY3DPEHPK3PXP',
      uri: 'otpauth://totp/DBS%20manager%3Asara?secret=JBSWY3DPEHPK3PXP',
      issuer: 'DBS manager',
      username: 'sara',
    });
    await expect(starting).resolves.toBe(true);
    expect(store.enrollment()?.secret).toBe('JBSWY3DPEHPK3PXP');

    const enrolling = store.enroll('123456');
    http
      .expectOne('/api/auth/two-factor/enrollment/confirm/')
      .flush({ identity: IDENTITY, recovery_codes: ['abcde-23456', 'fghjk-78923'] });
    await expect(enrolling).resolves.toBe(true);

    expect(store.isAuthenticated()).toBe(true);
    expect(store.enrollment()).toBeNull();
    expect(store.recoveryCodes()).toEqual(['abcde-23456', 'fghjk-78923']);
    store.dismissRecoveryCodes();
    expect(store.recoveryCodes()).toBeNull();
  });

  it('answers what the role may do, and forbids only once someone is signed in', async () => {
    expect(store.can('backups.take')).toBe(false);
    expect(store.forbids('backups.take')).toBe(false);

    await restoreAs(OPERATOR);

    expect(store.can('backups.take')).toBe(true);
    expect(store.forbids('backups.take')).toBe(false);
    expect(store.can('backups.restore')).toBe(false);
    expect(store.forbids('backups.restore')).toBe(true);
  });

  it('knows when the password must change', async () => {
    await restoreAs({ ...IDENTITY, password_change_required: true });

    expect(store.passwordChangeRequired()).toBe(true);
  });

  it('prefers the full name and falls back to the username', async () => {
    await restoreAs(IDENTITY);

    expect(store.displayName()).toBe('Sara Hassan');
  });

  it('gives a superuser every group and every permission', async () => {
    await restoreAs({ ...IDENTITY, is_superuser: true, groups: [], permissions: [] });

    expect(store.hasGroup('managers')).toBe(true);
    expect(store.hasPermission('orders.delete_order')).toBe(true);
  });

  it('does not grant a group the user is not in', async () => {
    await restoreAs(IDENTITY);

    expect(store.hasGroup('managers')).toBe(false);
    expect(store.hasAnyGroup(['managers', 'members'])).toBe(true);
  });
});
