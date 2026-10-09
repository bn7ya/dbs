import { HttpEventType, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { ARCHIVE_PLAN, FILE, JOB_ID, PLAN, SERVER_ID, UPLOADED_FILE, pageOf } from '../testing/backups.fixtures';
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

  it('lists one server a page at a time', async () => {
    const listing = firstValueFrom(api.list({ server: SERVER_ID, page: 2, page_size: 20 }));
    const request = http.expectOne(`/api/backups/?server=${SERVER_ID}&page=2&page_size=20`);
    expect(request.request.method).toBe('GET');
    request.flush(pageOf([FILE]));

    await expect(listing).resolves.toEqual(pageOf([FILE]));
  });

  it('starts a backup of the server and answers with its job', async () => {
    const taking = firstValueFrom(api.take(SERVER_ID));
    const request = http.expectOne('/api/backups/take/');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ server: SERVER_ID });
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

  it('starts a restore of a file and answers with its job', async () => {
    const body = { mode: 'replace', rehearse: false, account_password: 'secret', server_name: 'production-web' } as const;
    const restoring = firstValueFrom(api.restore(FILE.id, body));
    const request = http.expectOne(`/api/backups/${FILE.id}/restore/`);
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual(body);
    request.flush({ activity: JOB_ID }, { status: 202, statusText: 'Accepted' });

    await expect(restoring).resolves.toEqual({ activity: JOB_ID });
  });

  it('deletes a file and brings it back', async () => {
    const removing = firstValueFrom(api.remove(FILE.id));
    const removal = http.expectOne(`/api/backups/${FILE.id}/`);
    expect(removal.request.method).toBe('DELETE');
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

    it('sends the server and the file as form data', () => {
      api.upload(SERVER_ID, file()).subscribe();

      const request = http.expectOne('/api/backups/upload/');
      expect(request.request.method).toBe('POST');
      expect(request.request.reportProgress).toBe(true);
      const body = request.request.body as FormData;
      expect(body).toBeInstanceOf(FormData);
      expect(body.get('server')).toBe(SERVER_ID);
      const sent = body.get('file') as File;
      expect(sent.name).toBe(UPLOADED_FILE.name);
      expect(sent.size).toBe('backup bytes'.length);
      request.flush(UPLOADED_FILE, { status: 201, statusText: 'Created' });
    });

    it('reports the bytes sent as they go, then the file as stored', () => {
      const events: UploadEvent[] = [];
      api.upload(SERVER_ID, file()).subscribe((event) => events.push(event));

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
      const uploading = api.upload(SERVER_ID, file()).subscribe();
      const request = http.expectOne('/api/backups/upload/');

      uploading.unsubscribe();

      expect(request.cancelled).toBe(true);
    });
  });

  it('points a download at the file, without a request of its own', () => {
    expect(api.downloadUrl(FILE.id)).toBe(`/api/backups/${FILE.id}/download/`);
    http.expectNone(() => true);
  });

  describe('plans', () => {
    it("lists one server's plans a page at a time", async () => {
      const listing = firstValueFrom(api.plans({ server: SERVER_ID, page: 1, page_size: 20 }));
      const request = http.expectOne(`/api/backups/plans/?server=${SERVER_ID}&page=1&page_size=20`);
      expect(request.request.method).toBe('GET');
      request.flush(pageOf([PLAN]));

      await expect(listing).resolves.toEqual(pageOf([PLAN]));
    });

    it('adds a plan to a server', async () => {
      const plan = {
        server: SERVER_ID,
        kind: 'dbs',
        name: PLAN.name,
        interval_minutes: 1440,
        keep: 7,
        keep_remote: 1,
        enabled: true,
        paths: [],
        pattern: '',
      } as const;
      const creating = firstValueFrom(api.createPlan(plan));
      const request = http.expectOne('/api/backups/plans/');
      expect(request.request.method).toBe('POST');
      expect(request.request.body).toEqual(plan);
      request.flush(PLAN, { status: 201, statusText: 'Created' });

      await expect(creating).resolves.toEqual(PLAN);
    });

    it('adds a plan that archives folders, with its folders', async () => {
      const plan = {
        server: SERVER_ID,
        kind: 'archive',
        name: ARCHIVE_PLAN.name,
        interval_minutes: 10080,
        keep: 7,
        keep_remote: 1,
        enabled: true,
        paths: ['/srv/app/media', '/srv/app/uploads'],
        pattern: '',
      } as const;
      const creating = firstValueFrom(api.createPlan(plan));
      const request = http.expectOne('/api/backups/plans/');
      expect(request.request.body).toEqual(plan);
      request.flush(ARCHIVE_PLAN, { status: 201, statusText: 'Created' });

      await expect(creating).resolves.toEqual(ARCHIVE_PLAN);
    });

    it("changes a plan's folders", async () => {
      const updating = firstValueFrom(api.updatePlan(ARCHIVE_PLAN.id, { paths: ['/srv/app/media'] }));
      const request = http.expectOne(`/api/backups/plans/${ARCHIVE_PLAN.id}/`);
      expect(request.request.method).toBe('PATCH');
      expect(request.request.body).toEqual({ paths: ['/srv/app/media'] });
      request.flush({ ...ARCHIVE_PLAN, paths: ['/srv/app/media'] });

      await expect(updating).resolves.toEqual({ ...ARCHIVE_PLAN, paths: ['/srv/app/media'] });
    });

    it('changes only what it is given', async () => {
      const updating = firstValueFrom(api.updatePlan(PLAN.id, { keep: 14 }));
      const request = http.expectOne(`/api/backups/plans/${PLAN.id}/`);
      expect(request.request.method).toBe('PATCH');
      expect(request.request.body).toEqual({ keep: 14 });
      request.flush({ ...PLAN, keep: 14 });

      await expect(updating).resolves.toEqual({ ...PLAN, keep: 14 });
    });

    it('deletes a plan', async () => {
      const removing = firstValueFrom(api.removePlan(PLAN.id));
      const request = http.expectOne(`/api/backups/plans/${PLAN.id}/`);
      expect(request.request.method).toBe('DELETE');
      request.flush(null, { status: 204, statusText: 'No Content' });

      await expect(removing).resolves.toBeNull();
    });

    it('starts a run of a plan and answers with its job', async () => {
      const running = firstValueFrom(api.runPlan(PLAN.id));
      const request = http.expectOne(`/api/backups/plans/${PLAN.id}/run/`);
      expect(request.request.method).toBe('POST');
      request.flush({ activity: JOB_ID }, { status: 202, statusText: 'Accepted' });

      await expect(running).resolves.toEqual({ activity: JOB_ID });
    });
  });

  it("reads a server's unfinished jobs in one status from the activity list", async () => {
    const job = {
      id: JOB_ID,
      action: 'backup.run',
      status: 'running',
      target: PLAN.name,
      detail: { plan: PLAN.id },
    } as const;
    const reading = firstValueFrom(api.unfinishedJobs(SERVER_ID, 'running'));
    const request = http.expectOne(`/api/activity/?server=${SERVER_ID}&status=running&page=1&page_size=100`);
    expect(request.request.method).toBe('GET');
    request.flush(pageOf([job]));

    await expect(reading).resolves.toEqual(pageOf([job]));
  });
});
