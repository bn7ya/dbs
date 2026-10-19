import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { APPLICATION, SERVER_ID, SUMMARY, pageOf } from '../testing/applications.fixtures';
import { ApplicationsApi } from './applications.api';

const DETAIL = `/api/applications/${APPLICATION.id}/`;

describe('ApplicationsApi', () => {
  let api: ApplicationsApi;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(ApplicationsApi);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
  });

  it('lists a page, sending the search and the server only when there are some', async () => {
    const listing = firstValueFrom(api.list({ search: '', server: null, page: 2, page_size: 20 }));
    http.expectOne('/api/applications/?page=2&page_size=20').flush(pageOf([SUMMARY]));
    await expect(listing).resolves.toEqual(pageOf([SUMMARY]));

    void firstValueFrom(api.list({ search: 'shop', server: SERVER_ID, page: 1, page_size: 20 }));
    http.expectOne(`/api/applications/?page=1&page_size=20&search=shop&server=${SERVER_ID}`).flush(pageOf([]));
  });

  it('creates, reads, updates and removes one application', () => {
    const { id: _id, server: _server, ...settings } = APPLICATION;
    void firstValueFrom(api.create({ ...settings, server: SERVER_ID, discovered: true }));
    const post = http.expectOne('/api/applications/');
    expect(post.request.method).toBe('POST');
    expect(post.request.body).toMatchObject({ server: SERVER_ID, discovered: true, name: 'shop' });

    void firstValueFrom(api.get(APPLICATION.id));
    expect(http.expectOne(DETAIL).request.method).toBe('GET');

    void firstValueFrom(api.update(APPLICATION.id, { name: 'shop 2', account_password: 'secret' }));
    const patch = http.expectOne(DETAIL);
    expect(patch.request.method).toBe('PATCH');
    expect(patch.request.body).toEqual({ name: 'shop 2', account_password: 'secret' });

    void firstValueFrom(api.remove(APPLICATION.id, 'hunter2'));
    const removal = http.expectOne(DETAIL);
    expect(removal.request.method).toBe('DELETE');
    expect(removal.request.body).toEqual({ account_password: 'hunter2' });
  });

  it('discovers, checks and handles the passphrase on the application’s own action URLs', () => {
    void firstValueFrom(api.discover({ server: SERVER_ID, folder: '/srv/shop' }));
    const discover = http.expectOne('/api/applications/discover/');
    expect(discover.request.body).toEqual({ server: SERVER_ID, folder: '/srv/shop' });

    void firstValueFrom(api.check(APPLICATION.id));
    expect(http.expectOne(`${DETAIL}check/`).request.method).toBe('POST');

    void firstValueFrom(api.revealPassphrase(APPLICATION.id, 'secret'));
    expect(http.expectOne(`${DETAIL}passphrase/`).request.body).toEqual({ password: 'secret' });

    void firstValueFrom(api.capturePassphrase(APPLICATION.id));
    expect(http.expectOne(`${DETAIL}passphrase/capture/`).request.body).toEqual({});
  });

  it('takes a backup, reads its server and browses the server’s folders', () => {
    void firstValueFrom(api.takeBackup(APPLICATION.id));
    expect(http.expectOne('/api/backups/take/').request.body).toEqual({ application: APPLICATION.id });

    void firstValueFrom(api.server(SERVER_ID));
    expect(http.expectOne(`/api/servers/${SERVER_ID}/`).request.method).toBe('GET');

    void firstValueFrom(api.browse({ server: SERVER_ID, path: null, page: 1, page_size: 50 }));
    http.expectOne(`/api/servers/${SERVER_ID}/browse/?page=1&page_size=50`).flush({});

    void firstValueFrom(api.browse({ server: SERVER_ID, path: '/srv/shop', page: 2, page_size: 50 }));
    const request = http.expectOne((r) => r.url === `/api/servers/${SERVER_ID}/browse/`);
    expect(request.request.params.get('path')).toBe('/srv/shop');
    request.flush({});
  });
});
