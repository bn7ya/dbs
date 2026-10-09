import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { SetupStore } from './setup.store';

describe('SetupStore', () => {
  let store: SetupStore;
  let http: HttpTestingController;

  const request = { token: 'abc', username: 'sara', password: 'a long passphrase' };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    store = TestBed.inject(SetupStore);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
  });

  it('asks the backend once and keeps the answer', async () => {
    const first = store.check();
    http.expectOne('/api/setup/').flush({ needed: true });

    await expect(first).resolves.toBe(true);
    await expect(store.check()).resolves.toBe(true);
    expect(store.needed()).toBe(true);
  });

  it('reads an unreachable backend as no setup, and asks again next time', async () => {
    const first = store.check();
    http.expectOne('/api/setup/').flush(null, { status: 0, statusText: 'Unknown Error' });
    await expect(first).resolves.toBe(false);

    const second = store.check();
    http.expectOne('/api/setup/').flush({ needed: false });
    await expect(second).resolves.toBe(false);
  });

  it('primes CSRF, posts the account and ends the setup', async () => {
    const creating = store.complete(request);
    http.expectOne('/api/auth/csrf/').flush(null);

    const post = await vi.waitFor(() => http.expectOne('/api/setup/'));
    expect(post.request.method).toBe('POST');
    expect(post.request.body).toEqual(request);
    post.flush({ username: 'sara' }, { status: 201, statusText: 'Created' });

    await expect(creating).resolves.toBe(true);
    expect(store.needed()).toBe(false);
    expect(store.error()).toBeNull();
    expect(store.busy()).toBe(false);
  });

  it('holds a refused key as the error and keeps the setup open', async () => {
    const opening = store.check();
    http.expectOne('/api/setup/').flush({ needed: true });
    await opening;

    const creating = store.complete(request);
    http.expectOne('/api/auth/csrf/').flush(null);
    (await vi.waitFor(() => http.expectOne('/api/setup/'))).flush(
      { error: { code: 'setup_token_invalid', message: 'Server prose' } },
      { status: 403, statusText: 'Forbidden' },
    );

    await expect(creating).resolves.toBe(false);
    expect(store.error()?.code).toBe('setup_token_invalid');
    expect(store.needed()).toBe(true);
  });

  it('closes the setup when an account already exists', async () => {
    const opening = store.check();
    http.expectOne('/api/setup/').flush({ needed: true });
    await opening;

    const creating = store.complete(request);
    http.expectOne('/api/auth/csrf/').flush(null);
    (await vi.waitFor(() => http.expectOne('/api/setup/'))).flush(
      { error: { code: 'setup_done', message: 'Server prose' } },
      { status: 409, statusText: 'Conflict' },
    );

    await expect(creating).resolves.toBe(false);
    expect(store.needed()).toBe(false);
    await expect(store.check()).resolves.toBe(false);
  });
});
