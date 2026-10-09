import { HttpEventType, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { FILE, FOLDER, ROOT, SERVER_ID, listingOf } from '../testing/files.fixtures';
import { FilesApi } from './files.api';
import type { UploadEvent } from './files.types';

describe('FilesApi', () => {
  let api: FilesApi;
  let http: HttpTestingController;

  const base = `/api/files/${SERVER_ID}/`;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(FilesApi);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
  });

  it('lists the first allowed folder when no path is given', async () => {
    const listing = firstValueFrom(api.list({ server: SERVER_ID, path: null, page: 1, page_size: 50 }));
    const request = http.expectOne(`${base}?page=1&page_size=50`);
    expect(request.request.method).toBe('GET');
    expect(request.request.params.has('path')).toBe(false);
    request.flush(listingOf([FOLDER, FILE]));

    await expect(listing).resolves.toEqual(listingOf([FOLDER, FILE]));
  });

  it('lists a folder a page at a time, its path encoded whatever it holds', async () => {
    const path = '/srv/app/media/a b+c&d=e?#';
    const listing = firstValueFrom(api.list({ server: SERVER_ID, path, page: 2, page_size: 100 }));
    const request = http.expectOne((each) => each.url === base);
    expect(request.request.params.get('path')).toBe(path);
    expect(request.request.params.get('page')).toBe('2');
    expect(request.request.urlWithParams).toContain('a%20b%2Bc%26d=e?%23');
    request.flush(listingOf([], { path }));

    await expect(listing).resolves.toEqual(listingOf([], { path }));
  });

  it('points a download at the file, without a request of its own', () => {
    expect(api.downloadUrl(SERVER_ID, FILE.path)).toBe(
      `${base}download/?path=%2Fsrv%2Fapp%2Fmedia%2Freport%202026%2Bfinal.pdf`,
    );
    http.expectNone(() => true);
  });

  it('creates a folder inside another', async () => {
    const creating = firstValueFrom(api.createFolder(SERVER_ID, { path: ROOT, name: 'photos' }));
    const request = http.expectOne(`${base}folders/`);
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ path: ROOT, name: 'photos' });
    request.flush(FOLDER, { status: 201, statusText: 'Created' });

    await expect(creating).resolves.toEqual(FOLDER);
  });

  it('deletes by path', async () => {
    const removing = firstValueFrom(api.remove(SERVER_ID, FILE.path));
    const request = http.expectOne((each) => each.url === base);
    expect(request.request.method).toBe('DELETE');
    expect(request.request.params.get('path')).toBe(FILE.path);
    request.flush(null, { status: 204, statusText: 'No Content' });

    await expect(removing).resolves.toBeNull();
  });

  describe('uploading a file', () => {
    const file = (): File => new File(['file bytes'], FILE.name);

    it('sends the folder and the file as form data', () => {
      api.upload(SERVER_ID, ROOT, file()).subscribe();

      const request = http.expectOne(`${base}upload/`);
      expect(request.request.method).toBe('POST');
      expect(request.request.reportProgress).toBe(true);
      const body = request.request.body as FormData;
      expect(body.get('path')).toBe(ROOT);
      expect((body.get('file') as File).name).toBe(FILE.name);
      request.flush(FILE, { status: 201, statusText: 'Created' });
    });

    it('reports the bytes sent as they go, then the file as written', () => {
      const events: UploadEvent[] = [];
      api.upload(SERVER_ID, ROOT, file()).subscribe((event) => events.push(event));

      const request = http.expectOne(`${base}upload/`);
      request.event({ type: HttpEventType.Sent });
      request.event({ type: HttpEventType.UploadProgress, loaded: 4, total: 10 });
      // A body the browser could not measure: the file's own size stands in for the total.
      request.event({ type: HttpEventType.UploadProgress, loaded: 6 });
      request.flush(FILE, { status: 201, statusText: 'Created' });

      expect(events).toEqual([
        { kind: 'progress', sent: 4, total: 10 },
        { kind: 'progress', sent: 6, total: 'file bytes'.length },
        { kind: 'uploaded', entry: FILE },
      ]);
    });

    it('aborts the request when the upload is dropped', () => {
      const uploading = api.upload(SERVER_ID, ROOT, file()).subscribe();
      const request = http.expectOne(`${base}upload/`);

      uploading.unsubscribe();

      expect(request.cancelled).toBe(true);
    });
  });
});
