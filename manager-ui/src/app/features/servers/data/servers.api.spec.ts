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

    void firstValueFrom(api.remove(SERVER.id));
    expect(http.expectOne(detail).request.method).toBe('DELETE');
  });

  it('fetches a host key without pinning it', () => {
    void firstValueFrom(api.fingerprint({ host: 'web-1.example.com', port: 2222 }));
    const request = http.expectOne('/api/servers/fingerprint/');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ host: 'web-1.example.com', port: 2222 });
  });

  it('checks, re-pins and reveals on the server’s own action URLs', () => {
    void firstValueFrom(api.check(SERVER.id));
    const check = http.expectOne(`/api/servers/${SERVER.id}/check/`);
    expect(check.request.method).toBe('POST');

    void firstValueFrom(api.repinHostKey(SERVER.id, { host_key: 'line', password: 'secret' }));
    const repin = http.expectOne(`/api/servers/${SERVER.id}/host-key/`);
    expect(repin.request.method).toBe('POST');
    expect(repin.request.body).toEqual({ host_key: 'line', password: 'secret' });

    void firstValueFrom(api.revealPassphrase(SERVER.id, 'secret'));
    const reveal = http.expectOne(`/api/servers/${SERVER.id}/passphrase/`);
    expect(reveal.request.method).toBe('POST');
    expect(reveal.request.body).toEqual({ password: 'secret' });
  });
});
