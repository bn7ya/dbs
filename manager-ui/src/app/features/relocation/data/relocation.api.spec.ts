import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { APPLICATIONS, PLAN_ID, SERVERS, SHOP, SOURCE, SOURCE_SERVER, TARGET, pageOf } from '../testing/relocation.fixtures';
import { RelocationApi } from './relocation.api';
import type { ServerMoveRequest } from './relocation.types';

describe('RelocationApi', () => {
  let api: RelocationApi;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(RelocationApi);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
  });

  it('reads the server that moves, every server and the first page of its applications', async () => {
    const reading = firstValueFrom(api.server(SOURCE));
    void firstValueFrom(api.servers());
    void firstValueFrom(api.applications(SOURCE));

    http.expectOne(`/api/servers/${SOURCE}/`).flush(SOURCE_SERVER);
    http.expectOne('/api/servers/?page=1&page_size=100').flush(pageOf(SERVERS));
    http.expectOne(`/api/applications/?server=${SOURCE}&page=1&page_size=100`).flush(pageOf(APPLICATIONS));
    await expect(reading).resolves.toEqual(SOURCE_SERVER);
  });

  it('starts a move on the server that moves and answers with its job', async () => {
    const body: ServerMoveRequest = {
      target_server: TARGET,
      applications: [{ application: SHOP, name: 'Shop', folder: '/srv/shop', skip_volumes: [], copy_plans: true }],
      rehearsal: true,
      password: '',
      confirm_name: '',
      sudo_password: '',
      source_sudo_password: '',
    };
    const starting = firstValueFrom(api.move(SOURCE, body));

    const request = http.expectOne(`/api/servers/${SOURCE}/move/`);
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual(body);
    request.flush({ activity: PLAN_ID }, { status: 202, statusText: 'Accepted' });
    await expect(starting).resolves.toEqual({ activity: PLAN_ID });
  });
});
