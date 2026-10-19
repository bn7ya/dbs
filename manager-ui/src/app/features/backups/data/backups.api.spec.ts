import { HttpEventType, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  APPLICATIONS,
  APPLICATION_ID,
  DASHBOARD,
  FILE,
  JOB_ID,
  UPLOADED_FILE,
  pageOf,
  unfinished,
} from '../testing/backups.fixtures';
import { BackupsApi } from './backups.api';
import type { UploadEvent } from './backups.types';

describe('BackupsApi', () => {
  let api: BackupsApi;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(BackupsApi);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
  });

  it('lists one application a page at a time', async () => {
    const listing = firstValueFrom(api.list({ application: APPLICATION_ID, page: 2, page_size: 20 }));
    const request = http.expectOne(`/api/backups/?page=2&page_size=20&application=${APPLICATION_ID}`);
    expect(request.request.method).toBe('GET');
    request.flush(pageOf([FILE]));

    await expect(listing).resolves.toEqual(pageOf([FILE]));
  });

  it("lists every application's files when it names none", async () => {
    const listing = firstValueFrom(api.list({ application: null, page: 1, page_size: 50 }));
    const request = http.expectOne('/api/backups/?page=1&page_size=50');
    expect(request.request.params.has('application')).toBe(false);
    request.flush(pageOf([FILE]));

    await expect(listing).resolves.toEqual(pageOf([FILE]));
  });

  it('starts a backup of the application and answers with its job', async () => {
    const taking = firstValueFrom(api.take(APPLICATION_ID));
    const request = http.expectOne('/api/backups/take/');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ application: APPLICATION_ID });
    request.flush({ activity: JOB_ID }, { status: 202, statusText: 'Accepted' });

    await expect(taking).resolves.toEqual({ activity: JOB_ID });
  });

  it('starts a check of one file', async () => {
    const verifying = firstValueFrom(api.verify(FILE.id));
    const request = http.expectOne(`/api/backups/${FILE.id}/verify/`);
    expect(request.request.method).toBe('POST');
    request.flush({ activity: JOB_ID }, { status: 202, statusText: 'Accepted' });

    await expect(verifying).resolves.toEqual({ activity: JOB_ID });
  });

  it('starts a restore of a file, onto another application when asked, and answers with its job', async () => {
    const body = {
      mode: 'replace',
      rehearse: false,
      account_password: 'secret',
      application_name: 'blog',
      target_application: APPLICATIONS[1].id,
    } as const;
    const restoring = firstValueFrom(api.restore(FILE.id, body));
    const request = http.expectOne(`/api/backups/${FILE.id}/restore/`);
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual(body);
    request.flush({ activity: JOB_ID }, { status: 202, statusText: 'Accepted' });

    await expect(restoring).resolves.toEqual({ activity: JOB_ID });
  });

  it('deletes a file with the password and brings it back', async () => {
    const removing = firstValueFrom(api.remove(FILE.id, 'hunter2'));
    const removal = http.expectOne(`/api/backups/${FILE.id}/`);
    expect(removal.request.method).toBe('DELETE');
    expect(removal.request.body).toEqual({ account_password: 'hunter2' });
    removal.flush(null, { status: 204, statusText: 'No Content' });
    await removing;

    const restoring = firstValueFrom(api.undoDelete(FILE.id));
    const undo = http.expectOne(`/api/backups/${FILE.id}/undo-delete/`);
    expect(undo.request.method).toBe('POST');
    undo.flush(FILE);
    await expect(restoring).resolves.toEqual(FILE);
  });

  describe('uploading a file', () => {
    const file = (): File => new File(['backup bytes'], UPLOADED_FILE.name);

    it('sends the application and the file as form data', () => {
      api.upload(APPLICATION_ID, file()).subscribe();

      const request = http.expectOne('/api/backups/upload/');
      expect(request.request.method).toBe('POST');
      expect(request.request.reportProgress).toBe(true);
      const body = request.request.body as FormData;
      expect(body).toBeInstanceOf(FormData);
      expect(body.get('application')).toBe(APPLICATION_ID);
      const sent = body.get('file') as File;
      expect(sent.name).toBe(UPLOADED_FILE.name);
      expect(sent.size).toBe('backup bytes'.length);
      request.flush(UPLOADED_FILE, { status: 201, statusText: 'Created' });
    });

    it('reports the bytes sent as they go, then the file as stored', () => {
      const events: UploadEvent[] = [];
      api.upload(APPLICATION_ID, file()).subscribe((event) => events.push(event));

      const request = http.expectOne('/api/backups/upload/');
      request.event({ type: HttpEventType.Sent });
      request.event({ type: HttpEventType.UploadProgress, loaded: 120, total: 480 });
      // A body the browser could not measure: the file's own size stands in for the total.
      request.event({ type: HttpEventType.UploadProgress, loaded: 6 });
      request.event({ type: HttpEventType.DownloadProgress, loaded: 40 });
      request.flush(UPLOADED_FILE, { status: 201, statusText: 'Created' });

      expect(events).toEqual([
        { kind: 'progress', sent: 120, total: 480 },
        { kind: 'progress', sent: 6, total: 'backup bytes'.length },
        { kind: 'uploaded', file: UPLOADED_FILE },
      ]);
    });

    it('aborts the request when the upload is dropped', () => {
      const uploading = api.upload(APPLICATION_ID, file()).subscribe();
      const request = http.expectOne('/api/backups/upload/');

      uploading.unsubscribe();

      expect(request.cancelled).toBe(true);
    });
  });

  it('points a download at the file, without a request of its own', () => {
    expect(api.downloadUrl(FILE.id)).toBe(`/api/backups/${FILE.id}/download/`);
    http.expectNone(() => true);
  });

  it('asks for a link to a file, sending the password', async () => {
    const linking = firstValueFrom(api.downloadLink(FILE.id, 'hunter2'));
    const request = http.expectOne(`/api/backups/${FILE.id}/download/`);
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ account_password: 'hunter2' });
    request.flush({ url: `/api/backups/${FILE.id}/download/?ticket=t1` });

    await expect(linking).resolves.toEqual({ url: `/api/backups/${FILE.id}/download/?ticket=t1` });
  });

  it('reads the applications to choose from, as many as one page holds', async () => {
    const reading = firstValueFrom(api.applications());
    const request = http.expectOne('/api/applications/?page=1&page_size=200');
    expect(request.request.method).toBe('GET');
    request.flush(pageOf(APPLICATIONS));

    await expect(reading).resolves.toEqual(pageOf(APPLICATIONS));
  });

  it("reads the manager's storage from the dashboard", async () => {
    const reading = firstValueFrom(api.storage());
    const request = http.expectOne('/api/dashboard/');
    expect(request.request.method).toBe('GET');
    request.flush(DASHBOARD);

    await expect(reading).resolves.toEqual(DASHBOARD);
  });

  it("reads an application's unfinished jobs in one status, or every application's", async () => {
    const job = unfinished('backup.take');
    const one = firstValueFrom(api.unfinishedJobs(APPLICATION_ID, 'running'));
    http
      .expectOne(`/api/activity/?status=running&page=1&page_size=100&application=${APPLICATION_ID}`)
      .flush(pageOf([job]));
    await expect(one).resolves.toEqual(pageOf([job]));

    const every = firstValueFrom(api.unfinishedJobs(null, 'queued'));
    http.expectOne('/api/activity/?status=queued&page=1&page_size=100').flush(pageOf([job]));
    await expect(every).resolves.toEqual(pageOf([job]));
  });
});
