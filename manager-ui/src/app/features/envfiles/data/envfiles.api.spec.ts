import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { COMPARISON, CONTENT, ENV_PATH, OLDER, SERVER_ID, VERSION, pageOf } from '../testing/envfiles.fixtures';
import { EnvfilesApi } from './envfiles.api';
import { envFileName } from './envfiles.types';

describe('EnvfilesApi', () => {
  let api: EnvfilesApi;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(EnvfilesApi);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
  });

  it("lists one server's versions a page at a time", async () => {
    const listing = firstValueFrom(api.list({ server: SERVER_ID, page: 2, page_size: 20 }));
    const request = http.expectOne(`/api/envfiles/?server=${SERVER_ID}&page=2&page_size=20`);
    expect(request.request.method).toBe('GET');
    request.flush(pageOf([VERSION, OLDER], 22));

    await expect(listing).resolves.toEqual(pageOf([VERSION, OLDER], 22));
  });

  it('pulls the file of a server', async () => {
    const pulling = firstValueFrom(api.pull(SERVER_ID));
    const request = http.expectOne('/api/envfiles/pull/');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ server: SERVER_ID });
    request.flush({ created: true, version: VERSION });

    await expect(pulling).resolves.toEqual({ created: true, version: VERSION });
  });

  it('compares one version with another, from the older to the newer', async () => {
    const comparing = firstValueFrom(api.compare(OLDER.id, VERSION.id));
    const request = http.expectOne(`/api/envfiles/${OLDER.id}/compare/?to=${VERSION.id}`);
    expect(request.request.method).toBe('GET');
    request.flush(COMPARISON);

    await expect(comparing).resolves.toEqual(COMPARISON);
  });

  it("shows a version's content with the reader's password", async () => {
    const revealing = firstValueFrom(api.reveal(VERSION.id, 'hunter2'));
    const request = http.expectOne(`/api/envfiles/${VERSION.id}/reveal/`);
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ password: 'hunter2' });
    request.flush({ content: CONTENT });

    await expect(revealing).resolves.toEqual({ content: CONTENT });
  });

  it("pushes a version back with the reader's password", async () => {
    const pushing = firstValueFrom(api.push(OLDER.id, 'hunter2'));
    const request = http.expectOne(`/api/envfiles/${OLDER.id}/push/`);
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ password: 'hunter2' });
    request.flush({ version: { ...OLDER, source: 'pushed' } });

    await expect(pushing).resolves.toEqual({ version: { ...OLDER, source: 'pushed' } });
  });

  it("reads where the server's .env file is from the server itself", async () => {
    const reading = firstValueFrom(api.envPath(SERVER_ID));
    const request = http.expectOne(`/api/servers/${SERVER_ID}/`);
    expect(request.request.method).toBe('GET');
    request.flush({ id: SERVER_ID, name: 'web', env_path: ENV_PATH });

    await expect(reading).resolves.toBe(ENV_PATH);
  });
});

describe('envFileName', () => {
  it("is the base name of the version's path", () => {
    expect(envFileName('/srv/app/.env')).toBe('.env');
    expect(envFileName('/srv/app/production.env')).toBe('production.env');
  });

  it('is .env when the path names no file', () => {
    expect(envFileName('')).toBe('.env');
    expect(envFileName('/srv/app/')).toBe('.env');
  });
});
