import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { NADIA, OMAR, SARA } from '../testing/accounts.fixtures';
import { AccountsStore } from './accounts.store';

describe('AccountsStore', () => {
  let store: AccountsStore;
  let http: HttpTestingController;

  const loaded = async (): Promise<void> => {
    const loading = store.load();
    http.expectOne('/api/accounts/').flush([SARA, OMAR]);
    await loading;
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        AccountsStore,
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    store = TestBed.inject(AccountsStore);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
  });

  it('loads every account', async () => {
    expect(store.pending()).toBe(false);
    const loading = store.load();
    expect(store.pending()).toBe(true);
    http.expectOne('/api/accounts/').flush([SARA, OMAR]);
    await loading;

    expect(store.accounts().map((account) => account.username)).toEqual(['sara', 'omar']);
    expect(store.pending()).toBe(false);
  });

  it('adds a new account to the list', async () => {
    await loaded();

    const adding = store.create({ username: 'nadia', password: 'a long passphrase', role: 'viewer' });
    const request = http.expectOne('/api/accounts/');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ username: 'nadia', password: 'a long passphrase', role: 'viewer' });
    request.flush(NADIA, { status: 201, statusText: 'Created' });

    await expect(adding).resolves.toBe(true);
    expect(store.accounts()).toHaveLength(3);
  });

  it('replaces the row an action changed', async () => {
    await loaded();

    const changing = store.setRole(OMAR, 'admin');
    const request = http.expectOne('/api/accounts/2/');
    expect(request.request.method).toBe('PATCH');
    expect(request.request.body).toEqual({ role: 'admin' });
    request.flush({ ...OMAR, role: 'admin' });
    await changing;

    expect(store.accounts()[1].role).toBe('admin');
  });

  it('calls the endpoint each action needs', async () => {
    await loaded();

    const disabling = store.setActive(OMAR, false);
    const disable = http.expectOne('/api/accounts/2/');
    expect(disable.request.body).toEqual({ is_active: false });
    disable.flush(OMAR);
    const resetting = store.resetTwoFactor(OMAR);
    http.expectOne('/api/accounts/2/two-factor/reset/').flush(OMAR);
    const expiring = store.expirePassword(OMAR);
    http.expectOne('/api/accounts/2/password/expire/').flush(OMAR);
    const handing = store.handOver(OMAR, { password: 'secret', code: '123456' });
    const handOver = http.expectOne('/api/accounts/2/master/');
    expect(handOver.request.body).toEqual({ password: 'secret', code: '123456' });
    handOver.flush({ ...OMAR, role: 'master' });

    await Promise.all([disabling, resetting, expiring, handing]);
  });

  it('keeps a refusal for the form that asked', async () => {
    await loaded();

    const demoting = store.setRole(OMAR, 'viewer');
    http
      .expectOne('/api/accounts/2/')
      .flush({ error: { code: 'role_required', message: 'No' } }, { status: 403, statusText: 'Forbidden' });

    await expect(demoting).resolves.toBe(false);
    expect(store.formError()?.code).toBe('role_required');
    store.resetForm();
    expect(store.formError()).toBeNull();
  });
});
