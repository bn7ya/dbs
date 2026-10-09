import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { ENTRY, SERVER_ID, pageOf } from '../testing/activity.fixtures';
import { ActivityApi } from './activity.api';

describe('ActivityApi', () => {
  let api: ActivityApi;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(ActivityApi);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
  });

  it('lists a page with no filter on the query string when none is set', async () => {
    const listing = firstValueFrom(api.list({ page: 2, page_size: 20 }));
    const request = http.expectOne((r) => r.url === '/api/activity/');
    expect(request.request.method).toBe('GET');
    expect(request.request.params.get('page')).toBe('2');
    expect(request.request.params.get('page_size')).toBe('20');
    expect(request.request.params.keys().sort()).toEqual(['page', 'page_size']);
    request.flush(pageOf([ENTRY]));

    await expect(listing).resolves.toEqual(pageOf([ENTRY]));
  });

  it('sends the server, the action and the status when they are set', () => {
    void firstValueFrom(
      api.list({ server: SERVER_ID, action: 'server.check', status: 'failed', page: 1, page_size: 50 }),
    );

    http
      .expectOne(`/api/activity/?page=1&page_size=50&server=${SERVER_ID}&action=server.check&status=failed`)
      .flush(pageOf([]));
  });
});
