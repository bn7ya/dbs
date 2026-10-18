import { HttpEventType, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, type TestRequest } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { Subject, type Observable } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import { JobWatcher } from '@core/jobs/job-watcher';
import type { Job } from '@core/jobs/job.types';
import { Toaster } from '@shared/toaster/toaster';
import type { ToastMessage } from '@shared/toaster/toaster.types';
import type { BackupFile, UnfinishedJob } from '../data/backups.types';
import en from '../i18n/en.json';
import ar from '../i18n/ar.json';
import {
  APPLICATIONS,
  APPLICATION_ID,
  ARCHIVE_FILE,
  BLOG_FILE,
  COLLECTED_FILE,
  DASHBOARD,
  FILE,
  JOB_ID,
  OTHER_APPLICATION_ID,
  OTHER_SERVER_ID,
  PLAN,
  SERVER_ID,
  UPLOADED_FILE,
  VERIFIED,
  jobOf,
  pageOf,
  unfinished,
} from '../testing/backups.fixtures';
import type { Opening } from '../testing/backups.fixtures.types';
import { BackupsStore } from './backups.store';

const OTHER_JOB = 10;
const THIRD_JOB = 11;

// Stands in for the poller: the spec says when a job moves and when it ends.
class FakeJobWatcher {
  readonly followed = new Map<number, Subject<Job>>();
  readonly watched: number[] = [];

  watch(id: number): Observable<Job> {
    const job = new Subject<Job>();
    this.followed.set(id, job);
    this.watched.push(id);
    return job.asObservable();
  }

  report(job: Job): void {
    const stream = this.followed.get(job.id);
    stream?.next(job);
    if (job.status === 'succeeded' || job.status === 'failed') {
      stream?.complete();
    }
  }
}

describe('BackupsStore', () => {
  let store: BackupsStore;
  let http: HttpTestingController;
  let jobs: FakeJobWatcher;
  let toasts: MockInstance<(message: ToastMessage) => void>;

  const listRequest = (): TestRequest => http.expectOne((request) => request.url === '/api/backups/');
  const jobsRequest = (status: string): TestRequest =>
    http.expectOne((request) => request.url === '/api/activity/' && request.params.get('status') === status);
  const applicationsRequest = (): TestRequest => http.expectOne((request) => request.url === '/api/applications/');
  const storageRequest = (): TestRequest => http.expectOne('/api/dashboard/');

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const answerJobs = ({ running = [], queued = [] }: Opening = {}): void => {
    jobsRequest('running').flush(pageOf(running));
    jobsRequest('queued').flush(pageOf(queued));
  };

  const openWith = async (opening: Opening = {}, application = APPLICATION_ID): Promise<void> => {
    store.openApplication(application);
    TestBed.tick();
    listRequest().flush(pageOf(opening.files ?? [FILE]));
    answerJobs(opening);
    await settle();
  };

  const openEveryWith = async (opening: Opening = {}): Promise<void> => {
    store.openEvery();
    TestBed.tick();
    listRequest().flush(pageOf(opening.files ?? [FILE, BLOG_FILE]));
    applicationsRequest().flush(pageOf(APPLICATIONS));
    storageRequest().flush(DASHBOARD);
    answerJobs(opening);
    await settle();
  };

  const answerReload = async (results: readonly BackupFile[] = [FILE]): Promise<void> => {
    TestBed.tick();
    listRequest().flush(pageOf(results));
    await settle();
  };

  const lastToast = (): ToastMessage | undefined => toasts.mock.lastCall?.[0];

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [
        BackupsStore,
        { provide: JobWatcher, useClass: FakeJobWatcher },
        // The real interceptor: the store's contract is that it only ever sees an ApiError.
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    TestBed.inject(LocaleStore).register({ en, ar });
    store = TestBed.inject(BackupsStore);
    http = TestBed.inject(HttpTestingController);
    jobs = TestBed.inject(JobWatcher) as unknown as FakeJobWatcher;
    toasts = vi.spyOn(TestBed.inject(Toaster), 'add').mockReturnValue(undefined);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  describe("one application's files", () => {
    it('loads nothing until the page opens it', () => {
      TestBed.tick();

      http.expectNone(() => true);
      expect(store.files()).toEqual([]);
      expect(store.pending()).toBe(false);
    });

    it("lists the application's files a page at a time", async () => {
      store.openApplication(APPLICATION_ID);
      TestBed.tick();
      expect(store.pending()).toBe(true);

      const request = listRequest();
      expect(request.request.params.get('application')).toBe(APPLICATION_ID);
      expect(request.request.params.get('page')).toBe('1');
      expect(request.request.params.get('page_size')).toBe('20');
      request.flush(pageOf([FILE, VERIFIED], 41));
      answerJobs();
      await settle();

      expect(store.files()).toEqual([FILE, VERIFIED]);
      expect(store.count()).toBe(41);
      expect(store.pending()).toBe(false);
      expect(store.empty()).toBe(false);

      store.goToPage(2, 20);
      TestBed.tick();
      const next = listRequest();
      expect(next.request.params.get('page')).toBe('3');
      expect(store.files()).toEqual([FILE, VERIFIED]);
      next.flush(pageOf([VERIFIED], 41));
      await settle();
      expect(store.files()).toEqual([VERIFIED]);
    });

    it("never shows one application's files on another's tab", async () => {
      await openWith();

      store.openApplication(OTHER_APPLICATION_ID);
      TestBed.tick();
      const request = listRequest();
      expect(request.request.params.get('application')).toBe(OTHER_APPLICATION_ID);
      expect(request.request.params.get('page')).toBe('1');
      expect(store.files()).toEqual([]);
      expect(store.pending()).toBe(true);

      request.flush(pageOf([], 0));
      answerJobs();
      await settle();
      expect(store.empty()).toBe(true);
    });

    it('holds the failure as an ApiError and retries on reload', async () => {
      store.openApplication(APPLICATION_ID);
      TestBed.tick();
      listRequest().flush(
        { error: { code: 'unknown', message: 'Server prose' } },
        { status: 500, statusText: 'Server Error' },
      );
      answerJobs();
      await settle();
      expect(store.error()?.code).toBe('unknown');

      store.reload();
      await answerReload();
      expect(store.error()).toBeNull();
      expect(store.files()).toEqual([FILE]);
    });

    it('forgets the rows when the page closes', async () => {
      await openWith();

      store.close();
      TestBed.tick();

      expect(store.files()).toEqual([]);
    });
  });

  describe("every application's files", () => {
    it('lists them without naming an application, with the applications to filter by and the storage', async () => {
      store.openEvery();
      TestBed.tick();

      const request = listRequest();
      expect(request.request.params.has('application')).toBe(false);
      request.flush(pageOf([FILE, BLOG_FILE]));
      applicationsRequest().flush(pageOf(APPLICATIONS));
      storageRequest().flush(DASHBOARD);
      expect(jobsRequest('running').request.params.has('application')).toBe(false);
      jobsRequest('queued').flush(pageOf([]));
      await settle();

      expect(store.files()).toEqual([FILE, BLOG_FILE]);
      expect(store.applications()).toEqual(APPLICATIONS);
      expect(store.storage()).toEqual({
        total: 5_400_000,
        applications: [
          { id: OTHER_APPLICATION_ID, name: 'blog', server: OTHER_SERVER_ID, serverName: 'staging-web', bytes: 4_000_000 },
          { id: APPLICATION_ID, name: 'shop', server: SERVER_ID, serverName: 'production-web', bytes: 1_400_000 },
        ],
      });
    });

    it('filters by one application from the first page, without the rows of every one', async () => {
      await openEveryWith();
      store.goToPage(1, 20);
      TestBed.tick();
      listRequest().flush(pageOf([FILE], 41));
      await settle();

      store.filterBy(OTHER_APPLICATION_ID);
      TestBed.tick();
      const request = listRequest();
      expect(request.request.params.get('application')).toBe(OTHER_APPLICATION_ID);
      expect(request.request.params.get('page')).toBe('1');
      expect(store.files()).toEqual([]);
      expect(store.application()).toBe(OTHER_APPLICATION_ID);
      request.flush(pageOf([BLOG_FILE]));
      await settle();
      expect(store.files()).toEqual([BLOG_FILE]);

      store.filterBy(null);
      TestBed.tick();
      expect(listRequest().request.params.has('application')).toBe(false);
    });

    it("takes no filter on one application's tab", async () => {
      await openWith();

      store.filterBy(OTHER_APPLICATION_ID);
      TestBed.tick();

      http.expectNone((request) => request.url === '/api/backups/');
      expect(store.application()).toBe(APPLICATION_ID);
    });

    it('holds a failure to read the storage, and retries', async () => {
      store.openEvery();
      TestBed.tick();
      listRequest().flush(pageOf([FILE]));
      applicationsRequest().flush(pageOf(APPLICATIONS));
      storageRequest().flush({ error: { code: 'unknown', message: 'Server prose' } }, { status: 500, statusText: 'Error' });
      answerJobs();
      await settle();
      expect(store.storageError()?.code).toBe('unknown');
      expect(store.storage()).toBeNull();

      store.reloadStorage();
      TestBed.tick();
      storageRequest().flush(DASHBOARD);
      await settle();
      expect(store.storageError()).toBeNull();
      expect(store.storage()?.total).toBe(5_400_000);
    });

    it('reads the storage again once a backup is deleted', async () => {
      await openEveryWith();

      const removing = store.remove(BLOG_FILE, 'hunter2');
      http.expectOne(`/api/backups/${BLOG_FILE.id}/`).flush(null, { status: 204, statusText: 'No Content' });
      await removing;
      TestBed.tick();
      listRequest().flush(pageOf([FILE]));
      storageRequest().flush({ ...DASHBOARD, storage_bytes: 1_400_000 });
      await settle();

      expect(store.storage()?.total).toBe(1_400_000);
      expect(store.deleted()).toEqual(BLOG_FILE);
    });

    it('follows the unfinished jobs of every application, each under its own application', async () => {
      await openEveryWith({
        running: [unfinished('backup.verify', { application: OTHER_APPLICATION_ID, target: BLOG_FILE.name })],
        queued: [unfinished('backup.restore', { id: OTHER_JOB, detail: { rehearse: true } })],
      });

      expect(jobs.watched).toEqual([JOB_ID, OTHER_JOB]);
      expect(store.isVerifying(BLOG_FILE)).toBe(true);
      expect(store.isVerifying(FILE)).toBe(false);
      expect(store.restoring(FILE)).toBe('rehearse');

      jobs.report(jobOf('backup.verify', { detail: { validation: 'verified' } }));
      expect(lastToast()).toEqual({ severity: 'success', summary: 'Check passed.', detail: `⁨${BLOG_FILE.name}⁩` });
      await answerReload([FILE, BLOG_FILE]);
    });
  });

  describe('taking a backup', () => {
    it('follows the job, then reloads the list and says it finished', async () => {
      await openWith({ files: [] });

      store.take();
      expect(store.taking()).toBe(true);
      expect(store.backingUp()).toBe(true);
      const request = http.expectOne('/api/backups/take/');
      expect(request.request.method).toBe('POST');
      expect(request.request.body).toEqual({ application: APPLICATION_ID });
      request.flush({ activity: JOB_ID }, { status: 202, statusText: 'Accepted' });

      jobs.report(jobOf('backup.take', { status: 'running', finished_at: null }));
      expect(store.taking()).toBe(true);
      expect(toasts).not.toHaveBeenCalled();

      jobs.report(jobOf('backup.take', { detail: { backup: FILE.id, size: FILE.size } }));
      expect(store.taking()).toBe(false);
      expect(lastToast()).toEqual({ severity: 'success', summary: 'Backup finished.' });
      await answerReload([FILE]);
      expect(store.files()).toEqual([FILE]);
    });

    it('warns that a backup whose connection broke is kept on the server', async () => {
      await openWith({ files: [] });

      store.take();
      http.expectOne('/api/backups/take/').flush({ activity: JOB_ID }, { status: 202, statusText: 'Accepted' });
      jobs.report(jobOf('backup.take', { detail: { outcome: 'kept_on_server', pulled: 0 } }));

      expect(lastToast()).toEqual({
        severity: 'warning',
        summary:
          'The connection broke before the backup arrived. The server keeps it, and the manager collects it at the next connection.',
      });
      await answerReload([]);
    });

    it('says a backup resumed after its connection broke', async () => {
      await openWith({ files: [] });

      store.take();
      http.expectOne('/api/backups/take/').flush({ activity: JOB_ID });
      jobs.report(jobOf('backup.take', { detail: { backup: FILE.id, resumed: true, pulled: 0, released: 1 } }));

      expect(lastToast()).toEqual({
        severity: 'success',
        summary: 'Backup finished. The connection broke on the way, and the backup resumed where it stopped.',
      });
      await answerReload();
    });

    it('says a backup the server lost while it arrived was not kept', async () => {
      await openWith();

      store.take();
      http.expectOne('/api/backups/take/').flush({ activity: JOB_ID });
      jobs.report(jobOf('backup.take', { status: 'failed', error_code: 'backup_lost_on_server' }));

      expect(lastToast()).toEqual({
        severity: 'danger',
        summary:
          'The connection broke while the backup was arriving, and the server did not finish it. Nothing was kept. Try again.',
      });
      await answerReload();
    });

    it("shows whether a running job's connection is alive, on its own application only", async () => {
      await openWith({ files: [] });
      store.take();
      http.expectOne('/api/backups/take/').flush({ activity: JOB_ID });
      expect(store.liveConnection()).toBeNull();

      const connection = { state: 'alive', last_activity_at: '2026-09-30T12:00:30Z', bytes: 4096 } as const;
      jobs.report(jobOf('backup.take', { status: 'running', finished_at: null, connection }));
      expect(store.liveConnection()).toEqual(connection);

      await openWith({ files: [] }, OTHER_APPLICATION_ID);
      expect(store.liveConnection()).toBeNull();
      await openWith();

      jobs.report(jobOf('backup.take', { connection: null }));
      expect(store.liveConnection()).toBeNull();
      await answerReload();
    });

    it('takes one backup of an application at a time, and shows it only on that application', async () => {
      await openWith();
      store.take();
      store.take();
      http.expectOne('/api/backups/take/').flush({ activity: JOB_ID });

      await openWith({ files: [] }, OTHER_APPLICATION_ID);
      expect(store.taking()).toBe(false);
      expect(store.backingUp()).toBe(false);

      await openWith();
      expect(store.taking()).toBe(true);

      jobs.report(jobOf('backup.take'));
      await answerReload();
    });

    it('says why the job failed, by its code', async () => {
      await openWith();
      store.take();
      http.expectOne('/api/backups/take/').flush({ activity: JOB_ID });

      jobs.report(jobOf('backup.take', { status: 'failed', error_code: 'interrupted' }));

      expect(store.taking()).toBe(false);
      expect(lastToast()).toEqual({ severity: 'danger', summary: 'The job stopped before it finished.' });
      await answerReload();
    });

    it('says a backup is already running when the backend refuses another', async () => {
      await openWith();
      store.take();
      http
        .expectOne('/api/backups/take/')
        .flush({ error: { code: 'backup_running', message: 'Server prose' } }, { status: 409, statusText: 'Conflict' });

      expect(store.taking()).toBe(false);
      expect(jobs.followed.size).toBe(0);
      expect(lastToast()?.severity).toBe('danger');
    });

    it('takes nothing on the page of every backup', async () => {
      await openEveryWith();

      store.take();

      http.expectNone('/api/backups/take/');
      expect(store.taking()).toBe(false);
    });
  });

  describe('uploading a file', () => {
    const chosen = (): File => new File(['abc'], UPLOADED_FILE.name);
    const uploadRequest = (): TestRequest => http.expectOne('/api/backups/upload/');
    const tooLarge = { severity: 'danger', summary: 'The file is too large to upload.', detail: `⁨${UPLOADED_FILE.name}⁩` };

    it('reports the share sent, then reloads the list and names the file', async () => {
      await openWith({ files: [] });

      store.uploadFile(chosen());
      expect(store.uploading()).toBe(true);
      expect(store.upload()?.name).toBe(UPLOADED_FILE.name);
      expect(store.uploadProgress()).toBe(0);
      const request = uploadRequest();
      expect((request.request.body as FormData).get('application')).toBe(APPLICATION_ID);

      request.event({ type: HttpEventType.UploadProgress, loaded: 1, total: 3 });
      expect(store.uploadProgress()).toBe(33);

      // Every byte sent: the backend is storing the file, and there is no share left to show.
      request.event({ type: HttpEventType.UploadProgress, loaded: 3, total: 3 });
      expect(store.uploadProgress()).toBeNull();
      expect(store.uploading()).toBe(true);
      expect(toasts).not.toHaveBeenCalled();

      request.flush(UPLOADED_FILE, { status: 201, statusText: 'Created' });
      expect(store.uploading()).toBe(false);
      expect(store.upload()).toBeNull();
      expect(lastToast()).toEqual({ severity: 'success', summary: 'Backup uploaded.', detail: `⁨${UPLOADED_FILE.name}⁩` });
      await answerReload([UPLOADED_FILE]);
      expect(store.files()).toEqual([UPLOADED_FILE]);
    });

    it('aborts the request on cancel, says nothing, and can upload again', async () => {
      await openWith();
      store.uploadFile(chosen());
      const request = uploadRequest();
      request.event({ type: HttpEventType.UploadProgress, loaded: 1, total: 3 });

      store.cancelUpload();

      expect(request.cancelled).toBe(true);
      expect(store.uploading()).toBe(false);
      expect(toasts).not.toHaveBeenCalled();

      store.uploadFile(chosen());
      uploadRequest().flush(UPLOADED_FILE, { status: 201, statusText: 'Created' });
      await answerReload();
    });

    it('uploads one file to an application at a time, and shows it only on that application', async () => {
      await openWith();
      store.uploadFile(chosen());
      store.uploadFile(chosen());
      const request = uploadRequest();

      await openWith({ files: [] }, OTHER_APPLICATION_ID);
      expect(store.uploading()).toBe(false);
      store.cancelUpload();
      expect(request.cancelled).toBe(false);

      await openWith();
      expect(store.uploading()).toBe(true);
      request.flush(UPLOADED_FILE, { status: 201, statusText: 'Created' });
      await answerReload();
    });

    it('says the file is too large, whether the backend or the proxy in front of it refused it', async () => {
      await openWith();

      store.uploadFile(chosen());
      uploadRequest().flush(
        { error: { code: 'upload_too_large', message: 'Server prose' } },
        { status: 413, statusText: 'Payload Too Large' },
      );
      expect(store.uploading()).toBe(false);
      expect(lastToast()).toEqual(tooLarge);

      store.uploadFile(chosen());
      uploadRequest().flush('<html><body><h1>413 Request Entity Too Large</h1></body></html>', {
        status: 413,
        statusText: 'Request Entity Too Large',
      });
      expect(lastToast()).toEqual(tooLarge);
    });

    it("says what is wrong with the file by the file's own code", async () => {
      await openWith();
      const refuse = (code: string): void =>
        uploadRequest().flush(
          { error: { code: 'invalid', message: 'Server prose', fields: { file: [code] } } },
          { status: 400, statusText: 'Bad Request' },
        );

      store.uploadFile(chosen());
      refuse('empty');
      expect(lastToast()?.summary).toBe('The file is empty.');

      store.uploadFile(chosen());
      refuse('invalid_name');
      expect(lastToast()?.summary).toBe('The name is not valid.');
    });
  });

  describe('verifying a backup', () => {
    it('marks the file busy, then reloads it and says it verified', async () => {
      await openWith({ files: [FILE] });

      store.verify(FILE);
      expect(store.isVerifying(FILE)).toBe(true);
      expect(store.isVerifying(VERIFIED)).toBe(false);
      http.expectOne(`/api/backups/${FILE.id}/verify/`).flush({ activity: JOB_ID });

      jobs.report(jobOf('backup.verify', { detail: { validation: 'verified' } }));

      expect(store.isVerifying(FILE)).toBe(false);
      expect(lastToast()).toEqual({ severity: 'success', summary: 'Check passed.', detail: `⁨${FILE.name}⁩` });
      await answerReload([{ ...FILE, validation: 'verified' }]);
      expect(store.files()[0].validation).toBe('verified');
    });

    it('reads a failed check as a result to show, not as a job error', async () => {
      await openWith({ files: [FILE] });
      store.verify(FILE);
      http.expectOne(`/api/backups/${FILE.id}/verify/`).flush({ activity: JOB_ID });

      jobs.report(jobOf('backup.verify', { detail: { validation: 'failed' } }));

      expect(lastToast()).toMatchObject({ severity: 'danger', summary: 'Check failed.' });
      await answerReload();
    });

    it('says why the check could not run', async () => {
      await openWith({ files: [FILE] });
      store.verify(FILE);
      http.expectOne(`/api/backups/${FILE.id}/verify/`).flush({ activity: JOB_ID });

      jobs.report(jobOf('backup.verify', { status: 'failed', error_code: 'host_key_changed' }));

      expect(lastToast()).toEqual({ severity: 'danger', summary: 'The server presented a different host key.' });
      await answerReload();
    });
  });

  describe('restoring a backup', () => {
    const REHEARSAL = { mode: 'merge', rehearse: true } as const;
    const FOR_REAL = {
      mode: 'replace',
      rehearse: false,
      account_password: 'secret',
      application_name: 'shop',
    } as const;

    const restored = (detail: Record<string, unknown>): Job =>
      jobOf('backup.restore', {
        detail: { backup: FILE.id, mode: 'merge', rehearse: true, flushed: null, healed: false, ...detail },
      });

    it('marks the file as rehearsing, then says what a restore would load', async () => {
      await openWith({ files: [FILE] });

      const starting = store.restore(FILE, REHEARSAL);
      expect(store.sendingRestore()).toBe(true);
      const request = http.expectOne(`/api/backups/${FILE.id}/restore/`);
      expect(request.request.body).toEqual(REHEARSAL);
      request.flush({ activity: JOB_ID });
      await expect(starting).resolves.toBe(true);

      expect(store.sendingRestore()).toBe(false);
      expect(store.restoring(FILE)).toBe('rehearse');
      expect(store.restoring(VERIFIED)).toBeNull();

      jobs.report(restored({ records: 42, files: 3 }));

      expect(store.restoring(FILE)).toBeNull();
      expect(lastToast()).toEqual({
        severity: 'success',
        summary: 'Rehearsal finished. Nothing changed.',
        detail: 'Records: 42. Files: 3.',
      });
    });

    it('says what a replace cleared and loaded, and that a damaged copy was repaired', async () => {
      await openWith({ files: [FILE] });
      const starting = store.restore(FILE, FOR_REAL);
      http.expectOne(`/api/backups/${FILE.id}/restore/`).flush({ activity: JOB_ID });
      await starting;
      expect(store.restoring(FILE)).toBe('restore');

      jobs.report(restored({ mode: 'replace', rehearse: false, records: 12, files: 0, flushed: 9, healed: true }));

      expect(lastToast()).toEqual({
        severity: 'success',
        summary: 'Backup restored.',
        detail: 'Records: 12. Files: 0. Records cleared first: 9. A damaged copy in the backup was repaired.',
      });
    });

    it('leaves out a count the server did not print', async () => {
      await openWith({ files: [FILE] });
      const starting = store.restore(FILE, REHEARSAL);
      http.expectOne(`/api/backups/${FILE.id}/restore/`).flush({ activity: JOB_ID });
      await starting;

      jobs.report(restored({ records: null, files: null }));

      expect(lastToast()).toEqual({ severity: 'success', summary: 'Rehearsal finished. Nothing changed.' });
    });

    it('warns, with where it is, when the copy sent could not be removed', async () => {
      await openWith({ files: [FILE] });
      const starting = store.restore(FILE, REHEARSAL);
      http.expectOne(`/api/backups/${FILE.id}/restore/`).flush({ activity: JOB_ID });
      await starting;

      jobs.report(restored({ records: 1, files: 0, copy_left: '/var/backups/.dbs-restore-ab.dbs' }));

      expect(lastToast()).toEqual({
        severity: 'warning',
        summary: 'Rehearsal finished. Nothing changed.',
        detail: 'Records: 1. Files: 0. The copy sent to the server is still at ⁨/var/backups/.dbs-restore-ab.dbs⁩.',
      });
    });

    it('says why the restore failed, and on which file', async () => {
      await openWith({ files: [FILE] });
      const starting = store.restore(FILE, REHEARSAL);
      http.expectOne(`/api/backups/${FILE.id}/restore/`).flush({ activity: JOB_ID });
      await starting;

      jobs.report(jobOf('backup.restore', { status: 'failed', error_code: 'dbs_too_old' }));

      expect(store.restoring(FILE)).toBeNull();
      expect(lastToast()).toEqual({
        severity: 'danger',
        summary: 'django-dbs in this application is too old for this. Upgrade it to the version this manager runs.',
        detail: `⁨${FILE.name}⁩`,
      });
    });

    it('keeps a refused request for the form, and follows nothing', async () => {
      await openWith({ files: [FILE] });

      const starting = store.restore(FILE, { ...FOR_REAL, account_password: 'wrong' });
      http
        .expectOne(`/api/backups/${FILE.id}/restore/`)
        .flush(
          { error: { code: 'invalid_password', message: 'That password is not right.' } },
          { status: 400, statusText: 'Bad Request' },
        );

      await expect(starting).resolves.toBe(false);
      expect(store.restoreError()?.code).toBe('invalid_password');
      expect(store.restoring(FILE)).toBeNull();
      expect(jobs.watched).toEqual([]);

      store.resetRestoreForm();
      expect(store.restoreError()).toBeNull();
      TestBed.tick();
      applicationsRequest().flush(pageOf(APPLICATIONS));
      await settle();
      expect(store.applications()).toEqual(APPLICATIONS);
    });
  });

  describe('jobs already running when the page opens', () => {
    const run = unfinished('backup.run', { target: PLAN.name, detail: { plan: PLAN.id } });
    const take = unfinished('backup.take', { id: OTHER_JOB, status: 'queued', target: 'shop' });
    const check = unfinished('backup.verify', { id: THIRD_JOB, status: 'queued' });

    it("follows every backup and check of the application, with their busy state and their toasts", async () => {
      await openWith({
        files: [FILE],
        running: [run],
        queued: [take, check, unfinished('application.check', { id: 99, status: 'queued', target: 'shop' })],
      });

      expect(jobs.watched).toEqual([JOB_ID, OTHER_JOB, THIRD_JOB]);
      expect(store.backingUp()).toBe(true);
      expect(store.taking()).toBe(true);
      expect(store.isVerifying(FILE)).toBe(true);

      jobs.report(jobOf('backup.run'));
      expect(lastToast()).toEqual({ severity: 'success', summary: 'Backup finished.', detail: `⁨${PLAN.name}⁩` });
      await answerReload();

      jobs.report(jobOf('backup.verify', { id: THIRD_JOB, detail: { validation: 'verified' } }));
      expect(store.isVerifying(FILE)).toBe(false);
      expect(lastToast()).toEqual({ severity: 'success', summary: 'Check passed.', detail: `⁨${FILE.name}⁩` });
      await answerReload();

      jobs.report(jobOf('backup.take', { id: OTHER_JOB, status: 'failed', error_code: 'interrupted' }));
      expect(store.taking()).toBe(false);
      expect(store.backingUp()).toBe(false);
      expect(lastToast()).toEqual({ severity: 'danger', summary: 'The job stopped before it finished.' });
      await answerReload();
    });

    it('follows a restore picked up on open, rehearsal or not', async () => {
      const restore = unfinished('backup.restore', { detail: { backup: FILE.id, mode: 'replace', rehearse: false } });
      await openWith({ files: [FILE], running: [restore] });

      expect(store.restoring(FILE)).toBe('restore');

      jobs.report(
        jobOf('backup.restore', { detail: { ...restore.detail, records: 5, files: 1, flushed: 2, healed: false } }),
      );
      expect(store.restoring(FILE)).toBeNull();
      expect(lastToast()).toEqual({
        severity: 'success',
        summary: 'Backup restored.',
        detail: 'Records: 5. Files: 1. Records cleared first: 2.',
      });
    });

    it('marks the source file of a restore onto another application', async () => {
      const onto: UnfinishedJob = unfinished('backup.restore', {
        application: OTHER_APPLICATION_ID,
        detail: { rehearse: true, source_application: APPLICATION_ID, target_application: OTHER_APPLICATION_ID },
      });
      await openEveryWith({ running: [onto] });

      expect(store.restoring(FILE)).toBe('rehearse');
      expect(store.restoring({ ...FILE, application: OTHER_APPLICATION_ID })).toBeNull();
    });

    it('follows a job once, however often it is found', async () => {
      await openWith();
      store.take();
      http.expectOne('/api/backups/take/').flush({ activity: OTHER_JOB });

      store.close();
      TestBed.tick();
      await openWith({ running: [take, { ...take, status: 'running' }] });

      expect(jobs.watched).toEqual([OTHER_JOB]);

      jobs.report(jobOf('backup.take', { id: OTHER_JOB }));
      expect(toasts).toHaveBeenCalledTimes(1);
      await answerReload();
    });

    it('leaves the page as it is when the jobs cannot be read', async () => {
      store.openApplication(APPLICATION_ID);
      TestBed.tick();
      listRequest().flush(pageOf([FILE]));
      jobsRequest('running').flush(
        { error: { code: 'unknown', message: 'Server prose' } },
        { status: 500, statusText: 'Server Error' },
      );
      expect(jobsRequest('queued').cancelled).toBe(true);
      await settle();

      expect(jobs.watched).toEqual([]);
      expect(toasts).not.toHaveBeenCalled();
      expect(store.files()).toEqual([FILE]);
    });
  });

  describe('deleting a backup', () => {
    it('deletes it, reloads the list, and offers Undo on the application it was on', async () => {
      await openWith({ files: [FILE, VERIFIED] });

      const removing = store.remove(FILE, 'hunter2');
      expect(store.deleting().has(FILE.id)).toBe(true);
      const request = http.expectOne(`/api/backups/${FILE.id}/`);
      expect(request.request.body).toEqual({ account_password: 'hunter2' });
      request.flush(null, { status: 204, statusText: 'No Content' });

      await expect(removing).resolves.toBe(true);
      expect(store.deleting().has(FILE.id)).toBe(false);
      await answerReload([VERIFIED]);
      expect(store.files()).toEqual([VERIFIED]);
      expect(store.deleted()).toEqual(FILE);
      expect(toasts).not.toHaveBeenCalled();

      const undoing = store.undoDelete();
      expect(store.undoing()).toBe(true);
      http.expectOne(`/api/backups/${FILE.id}/undo-delete/`).flush(FILE);
      await undoing;
      expect(store.undoing()).toBe(false);
      expect(store.deleted()).toBeNull();
      expect(lastToast()).toEqual({ severity: 'success', summary: 'Deletion undone.' });
      await answerReload([FILE, VERIFIED]);
      expect(store.files()).toEqual([FILE, VERIFIED]);
    });

    it('lets the reader put the Undo offer away', async () => {
      await openWith({ files: [FILE] });

      const removing = store.remove(FILE, 'hunter2');
      http.expectOne(`/api/backups/${FILE.id}/`).flush(null, { status: 204, statusText: 'No Content' });
      await removing;
      await answerReload([]);

      store.dismissDeleted();
      expect(store.deleted()).toBeNull();
    });

    it('keeps why it could not be deleted for the password prompt, and keeps the row', async () => {
      await openWith({ files: [FILE] });

      const removing = store.remove(FILE, 'wrong');
      http
        .expectOne(`/api/backups/${FILE.id}/`)
        .flush({ error: { code: 'invalid_password', message: 'Server prose' } }, { status: 400, statusText: 'Bad Request' });

      await expect(removing).resolves.toBe(false);
      expect(store.deleting().has(FILE.id)).toBe(false);
      expect(store.deleteError()?.code).toBe('invalid_password');
      expect(toasts).not.toHaveBeenCalled();
      expect(store.files()).toEqual([FILE]);
    });
  });

  it('points a download at the file', () => {
    expect(store.downloadUrl(FILE)).toBe(`/api/backups/${FILE.id}/download/`);
  });

  it('trades the password for a link to a sealed file, and keeps a refusal for the prompt', async () => {
    const refusing = store.downloadLink(ARCHIVE_FILE, 'wrong');
    http
      .expectOne(`/api/backups/${ARCHIVE_FILE.id}/download/`)
      .flush({ error: { code: 'invalid_password', message: 'Server prose' } }, { status: 400, statusText: 'Bad Request' });
    await expect(refusing).resolves.toBeNull();
    expect(store.downloadError()?.code).toBe('invalid_password');

    const linking = store.downloadLink(COLLECTED_FILE, 'hunter2');
    expect(store.downloadError()).toBeNull();
    const request = http.expectOne(`/api/backups/${COLLECTED_FILE.id}/download/`);
    expect(request.request.body).toEqual({ account_password: 'hunter2' });
    request.flush({ url: '/api/backups/a/download/?ticket=t1' });
    await expect(linking).resolves.toBe('/api/backups/a/download/?ticket=t1');
  });
});
