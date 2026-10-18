import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { CREATE, SERVER, SUMMARY, pageOf } from '../testing/servers.fixtures';
import { ServersApi } from './servers.api';

describe('ServersApi', () => {
  let api: ServersApi;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(ServersApi);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
  });

  it('lists a page, sending the search only when there is one', async () => {
    const listing = firstValueFrom(api.list({ search: '', page: 2, page_size: 20 }));
    const request = http.expectOne((r) => r.url === '/api/servers/');
    expect(request.request.method).toBe('GET');
    expect(request.request.params.get('page')).toBe('2');
    expect(request.request.params.get('page_size')).toBe('20');
    expect(request.request.params.has('search')).toBe(false);
    request.flush(pageOf([SUMMARY]));
    await expect(listing).resolves.toEqual(pageOf([SUMMARY]));

    void firstValueFrom(api.list({ search: 'web', page: 1, page_size: 20 }));
    http.expectOne('/api/servers/?page=1&page_size=20&search=web').flush(pageOf([]));
  });

  it('creates with a POST to the collection', () => {
    void firstValueFrom(api.create(CREATE));
    const request = http.expectOne('/api/servers/');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual(CREATE);
    request.flush(SERVER, { status: 201, statusText: 'Created' });
  });

  it('reads, updates and deletes one server by id', () => {
    const detail = `/api/servers/${SERVER.id}/`;

    void firstValueFrom(api.get(SERVER.id));
    expect(http.expectOne(detail).request.method).toBe('GET');

    void firstValueFrom(api.update(SERVER.id, { name: 'Renamed' }));
    const patch = http.expectOne(detail);
    expect(patch.request.method).toBe('PATCH');
    expect(patch.request.body).toEqual({ name: 'Renamed' });

    void firstValueFrom(api.remove(SERVER.id, 'hunter2'));
    const removal = http.expectOne(detail);
    expect(removal.request.method).toBe('DELETE');
    expect(removal.request.body).toEqual({ account_password: 'hunter2' });
  });

  it('lists the host keys awaiting confirmation, and confirms or rejects one by id', () => {
    void firstValueFrom(api.hostKeyConfirmations());
    const listing = http.expectOne((request) => request.url === '/api/servers/host-keys/');
    expect(listing.request.method).toBe('GET');
    expect(listing.request.params.get('page_size')).toBe('100');

    void firstValueFrom(api.decideHostKey('9f3a1c2e', 'confirm'));
    expect(http.expectOne('/api/servers/host-keys/9f3a1c2e/confirm/').request.method).toBe('POST');

    void firstValueFrom(api.decideHostKey('9f3a1c2e', 'reject'));
    expect(http.expectOne('/api/servers/host-keys/9f3a1c2e/reject/').request.method).toBe('POST');
  });

  it('fetches a host key without pinning it', () => {
    void firstValueFrom(api.fingerprint({ host: 'web-1.example.com', port: 2222 }));
    const request = http.expectOne('/api/servers/fingerprint/');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ host: 'web-1.example.com', port: 2222 });
  });

  it('checks, merges, re-pins and reads the public key on the server’s own action URLs', () => {
    void firstValueFrom(api.check(SERVER.id));
    const check = http.expectOne(`/api/servers/${SERVER.id}/check/`);
    expect(check.request.method).toBe('POST');

    void firstValueFrom(api.merge(SERVER.id, { into: 'kept', account_password: 'secret' }));
    const merge = http.expectOne(`/api/servers/${SERVER.id}/merge/`);
    expect(merge.request.method).toBe('POST');
    expect(merge.request.body).toEqual({ into: 'kept', account_password: 'secret' });

    void firstValueFrom(api.repinHostKey(SERVER.id, { host_key: 'line', password: 'secret' }));
    const repin = http.expectOne(`/api/servers/${SERVER.id}/host-key/`);
    expect(repin.request.method).toBe('POST');
    expect(repin.request.body).toEqual({ host_key: 'line', password: 'secret' });

    void firstValueFrom(api.publicKey(SERVER.id));
    expect(http.expectOne(`/api/servers/${SERVER.id}/public-key/`).request.method).toBe('GET');
  });
});
