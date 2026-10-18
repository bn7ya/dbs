import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { CREATE, SERVER } from '../testing/servers.fixtures';
import { ServerWizardStore } from './server-wizard.store';

describe('ServerWizardStore', () => {
  let store: ServerWizardStore;
  let http: HttpTestingController;

  const created = async (extra: Record<string, unknown> = {}): Promise<void> => {
    const creating = store.create(CREATE);
    http.expectOne('/api/servers/').flush({ ...SERVER, ...extra }, { status: 201, statusText: 'Created' });
    await creating;
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        ServerWizardStore,
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    store = TestBed.inject(ServerWizardStore);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
  });

  it('reads the host key the server presents', async () => {
    const fetching = store.fetchHostKey({ host: 'web-1.example.com', port: 22 });
    expect(store.fetchingHostKey()).toBe(true);
    http
      .expectOne('/api/servers/fingerprint/')
      .flush({ key_type: 'ssh-ed25519', line: 'web-1 ssh-ed25519 AAAA', fingerprint: 'SHA256:abc' });

    await expect(fetching).resolves.toMatchObject({ fingerprint: 'SHA256:abc' });
    expect(store.fetchingHostKey()).toBe(false);
  });

  it('creates the server once and keeps the generated public key', async () => {
    await created({ public_key: 'ssh-ed25519 AAAA dbs', authorized_keys_hint: 'echo ... >> authorized_keys' });

    expect(store.server()?.id).toBe(SERVER.id);
    expect(store.publicKey()).toBe('ssh-ed25519 AAAA dbs');

    const reading = store.rereadPublicKey();
    http.expectOne(`/api/servers/${SERVER.id}/public-key/`).flush({ public_key: 'ssh-ed25519 BBBB dbs' });
    await reading;
    expect(store.publicKey()).toBe('ssh-ed25519 BBBB dbs');
  });

  it('keeps the field codes when the backend refuses the server', async () => {
    const creating = store.create(CREATE);
    http.expectOne('/api/servers/').flush(
      { error: { code: 'invalid', message: 'Server prose', fields: { name: ['name_taken'] } } },
      { status: 400, statusText: 'Bad Request' },
    );

    await expect(creating).resolves.toBeNull();
    expect(store.server()).toBeNull();
    expect(store.createError()?.fields?.['name']).toEqual(['name_taken']);
  });

  it('checks the server it created and keeps what it found', async () => {
    await created();

    const checking = store.check();
    expect(store.checking()).toBe(true);
    http.expectOne(`/api/servers/${SERVER.id}/check/`).flush({ ...SERVER, last_check_status: 'problem' });

    await expect(checking).resolves.toBe(true);
    expect(store.checked()?.last_check_status).toBe('problem');
  });

  it('keeps why a check could not sign in, and forgets the last result', async () => {
    await created();
    const first = store.check();
    http.expectOne(`/api/servers/${SERVER.id}/check/`).flush(SERVER);
    await first;

    const checking = store.check();
    http
      .expectOne(`/api/servers/${SERVER.id}/check/`)
      .flush({ error: { code: 'ssh_auth_failed', message: 'Server prose' } }, { status: 400, statusText: 'Bad Request' });

    await expect(checking).resolves.toBe(false);
    expect(store.checkError()?.code).toBe('ssh_auth_failed');
    expect(store.checked()).toBeNull();
  });

  it('checks nothing before the server exists', async () => {
    await expect(store.check()).resolves.toBe(false);
  });
});
