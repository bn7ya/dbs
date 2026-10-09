import { HttpEventType, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, type TestRequest } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { MessageService } from 'primeng/api';
import { Subject, type Observable } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import { JobWatcher } from '@core/jobs/job-watcher';
import type { Job } from '@core/jobs/job.types';
import { Toaster } from '@shared/toaster/toaster';
import type { ToastMessage } from '@shared/toaster/toaster.types';
import type { BackupFile, BackupPlan, PlanSettings, UnfinishedJob } from '../data/backups.types';
import en from '../i18n/en.json';
import ar from '../i18n/ar.json';
import {
  ARCHIVE_FILE,
  ARCHIVE_PLAN,
  COLLECTED_FILE,
  COLLECT_PLAN,
  FILE,
  JOB_ID,
  MANUAL_PLAN,
  PLAN,
  SERVER_ID,
  UPLOADED_FILE,
  VERIFIED,
  jobOf,
  pageOf,
} from '../testing/backups.fixtures';
import type { Opening } from '../testing/backups.fixtures.types';
import { BackupsStore } from './backups.store';

const OTHER_SERVER = '0f3c2b9e-1111-4c4f-9a43-7b1d2f0c0002';
const OTHER_JOB = '7a1e0c55-2222-4d1b-8f00-9c3e5b7d0010';
const THIRD_JOB = '7a1e0c55-2222-4d1b-8f00-9c3e5b7d0011';

const SETTINGS: PlanSettings = {
  name: 'django-dbs',
  interval_minutes: 1440,
  keep: 7,
  keep_remote: 1,
  enabled: true,
  paths: [],
  pattern: '',
};

// Stands in for the poller: the spec says when a job moves and when it ends.
class FakeJobWatcher {
  readonly followed = new Map<string, Subject<Job>>();
  readonly watched: string[] = [];

  watch(id: string): Observable<Job> {
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
  const plansRequest = (): TestRequest => http.expectOne((request) => request.url === '/api/backups/plans/');
  const jobsRequest = (status: string): TestRequest =>
    http.expectOne((request) => request.url === '/api/activity/' && request.params.get('status') === status);

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const answerPlansAndJobs = ({ plans = [PLAN], running = [], queued = [] }: Opening = {}): void => {
    plansRequest().flush(pageOf(plans));
    jobsRequest('running').flush(pageOf(running));
    jobsRequest('queued').flush(pageOf(queued));
  };

  const openWith = async (opening: Opening = {}, server = SERVER_ID): Promise<void> => {
    store.open(server);
    TestBed.tick();
    listRequest().flush(pageOf(opening.files ?? [FILE]));
    answerPlansAndJobs(opening);
    await settle();
  };

  const answerReload = async (results: readonly BackupFile[] = [FILE]): Promise<void> => {
    TestBed.tick();
    listRequest().flush(pageOf(results));
    await settle();
  };

  const answerPlansReload = async (results: readonly BackupPlan[] = [PLAN]): Promise<void> => {
    TestBed.tick();
    plansRequest().flush(pageOf(results));
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
        MessageService,
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

  describe('the files', () => {
    it('loads nothing until the page opens it', () => {
      TestBed.tick();

      http.expectNone(() => true);
      expect(store.files()).toEqual([]);
      expect(store.plans()).toEqual([]);
      expect(store.pending()).toBe(false);
      expect(store.plansPending()).toBe(false);
    });

    it("lists the server's files a page at a time", async () => {
      store.open(SERVER_ID);
      TestBed.tick();
      expect(store.pending()).toBe(true);

      const request = listRequest();
      expect(request.request.params.get('server')).toBe(SERVER_ID);
      expect(request.request.params.get('page')).toBe('1');
      expect(request.request.params.get('page_size')).toBe('20');
      request.flush(pageOf([FILE, VERIFIED], 41));
      answerPlansAndJobs();
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

    it("never shows one server's files or plans on another's tab", async () => {
      await openWith();

      store.open(OTHER_SERVER);
      TestBed.tick();
      const request = listRequest();
      expect(request.request.params.get('server')).toBe(OTHER_SERVER);
      expect(request.request.params.get('page')).toBe('1');
      expect(store.files()).toEqual([]);
      expect(store.plans()).toEqual([]);
      expect(store.pending()).toBe(true);
      expect(store.plansPending()).toBe(true);

      request.flush(pageOf([], 0));
      answerPlansAndJobs({ plans: [] });
      await settle();
      expect(store.empty()).toBe(true);
      expect(store.plansEmpty()).toBe(true);
    });

    it('holds the failure as an ApiError and retries on reload', async () => {
      store.open(SERVER_ID);
      TestBed.tick();
      listRequest().flush(
        { error: { code: 'unknown', message: 'Server prose' } },
        { status: 500, statusText: 'Server Error' },
      );
      answerPlansAndJobs();
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
      expect(store.plans()).toEqual([]);
    });
  });

  describe('the plans', () => {
    it("lists the server's plans", async () => {
      store.open(SERVER_ID);
      TestBed.tick();
      listRequest().flush(pageOf([FILE]));
      const request = plansRequest();
      expect(request.request.params.get('server')).toBe(SERVER_ID);
      expect(request.request.params.get('page')).toBe('1');
      expect(request.request.params.get('page_size')).toBe('20');
      request.flush(pageOf([PLAN, MANUAL_PLAN], 21));
      answerPlansAndJobsExceptPlans();
      await settle();

      expect(store.plans()).toEqual([PLAN, MANUAL_PLAN]);
      expect(store.planCount()).toBe(21);
      expect(store.plansEmpty()).toBe(false);

      store.goToPlanPage(1);
      TestBed.tick();
      const next = plansRequest();
      expect(next.request.params.get('page')).toBe('2');
      expect(store.plans()).toEqual([PLAN, MANUAL_PLAN]);
      next.flush(pageOf([MANUAL_PLAN], 21));
      await settle();
      expect(store.plans()).toEqual([MANUAL_PLAN]);
    });

    it('holds a failure to list them, and retries', async () => {
      store.open(SERVER_ID);
      TestBed.tick();
      listRequest().flush(pageOf([FILE]));
      plansRequest().flush(
        { error: { code: 'unknown', message: 'Server prose' } },
        { status: 500, statusText: 'Server Error' },
      );
      answerPlansAndJobsExceptPlans();
      await settle();
      expect(store.plansError()?.code).toBe('unknown');
      expect(store.files()).toEqual([FILE]);

      store.reloadPlans();
      await answerPlansReload();
      expect(store.plansError()).toBeNull();
      expect(store.plans()).toEqual([PLAN]);
    });

    it('adds a django-dbs plan to the server on screen, then reloads the plans and says so', async () => {
      await openWith({ plans: [] });

      const creating = store.createPlan('dbs', SETTINGS);
      expect(store.savingPlan()).toBe(true);
      const request = http.expectOne((each) => each.url === '/api/backups/plans/' && each.method === 'POST');
      expect(request.request.body).toEqual({ ...SETTINGS, server: SERVER_ID, kind: 'dbs' });
      request.flush(PLAN, { status: 201, statusText: 'Created' });

      await expect(creating).resolves.toEqual(PLAN);
      expect(store.savingPlan()).toBe(false);
      expect(lastToast()).toEqual({ severity: 'success', summary: 'Plan added.', detail: `⁨${PLAN.name}⁩` });
      await answerPlansReload([PLAN]);
      expect(store.plans()).toEqual([PLAN]);
    });

    it('adds a plan that archives folders, with its kind and its folders', async () => {
      await openWith({ plans: [] });

      const settings = { ...SETTINGS, name: 'Media', paths: ARCHIVE_PLAN.paths };
      const creating = store.createPlan('archive', settings);
      const request = http.expectOne((each) => each.url === '/api/backups/plans/' && each.method === 'POST');
      expect(request.request.body).toEqual({ ...settings, server: SERVER_ID, kind: 'archive' });
      request.flush(ARCHIVE_PLAN, { status: 201, statusText: 'Created' });

      await expect(creating).resolves.toEqual(ARCHIVE_PLAN);
      expect(lastToast()).toEqual({ severity: 'success', summary: 'Plan added.', detail: `⁨${ARCHIVE_PLAN.name}⁩` });
      await answerPlansReload([ARCHIVE_PLAN]);
    });

    it('adds a plan that collects existing files, with its folder and its pattern', async () => {
      await openWith({ plans: [] });

      const settings = { ...SETTINGS, name: 'Database dumps', keep_remote: 0, paths: COLLECT_PLAN.paths, pattern: '*.sql.gz' };
      const creating = store.createPlan('collect', settings);
      const request = http.expectOne((each) => each.url === '/api/backups/plans/' && each.method === 'POST');
      expect(request.request.body).toEqual({ ...settings, server: SERVER_ID, kind: 'collect' });
      request.flush(COLLECT_PLAN, { status: 201, statusText: 'Created' });

      await expect(creating).resolves.toEqual(COLLECT_PLAN);
      await answerPlansReload([COLLECT_PLAN]);
    });

    it('holds what the backend refused, field by field, until the form opens again', async () => {
      await openWith({ plans: [PLAN] });

      const creating = store.createPlan('dbs', SETTINGS);
      http
        .expectOne((each) => each.url === '/api/backups/plans/' && each.method === 'POST')
        .flush(
          { error: { code: 'invalid', message: 'Server prose', fields: { name: ['name_taken'] } } },
          { status: 400, statusText: 'Bad Request' },
        );

      await expect(creating).resolves.toBeNull();
      expect(store.planSaveError()?.fields).toEqual({ name: ['name_taken'] });
      expect(toasts).not.toHaveBeenCalled();

      store.resetPlanForm();
      expect(store.planSaveError()).toBeNull();
    });

    it("saves a plan's settings", async () => {
      await openWith();

      const changed = { ...SETTINGS, keep: 14 };
      const updating = store.updatePlan(PLAN, changed);
      const request = http.expectOne(`/api/backups/plans/${PLAN.id}/`);
      expect(request.request.method).toBe('PATCH');
      expect(request.request.body).toEqual(changed);
      request.flush({ ...PLAN, keep: 14 });

      await expect(updating).resolves.toEqual({ ...PLAN, keep: 14 });
      expect(lastToast()).toEqual({ severity: 'success', summary: 'Plan saved.', detail: `⁨${PLAN.name}⁩` });
      await answerPlansReload([{ ...PLAN, keep: 14 }]);
    });

    it('deletes a plan, then reloads the plans and says so', async () => {
      await openWith({ plans: [PLAN, MANUAL_PLAN] });

      const removing = store.removePlan(PLAN);
      expect(store.deletingPlans().has(PLAN.id)).toBe(true);
      http.expectOne(`/api/backups/plans/${PLAN.id}/`).flush(null, { status: 204, statusText: 'No Content' });

      await expect(removing).resolves.toBe(true);
      expect(store.deletingPlans().has(PLAN.id)).toBe(false);
      expect(lastToast()).toEqual({ severity: 'success', summary: 'Plan deleted.', detail: `⁨${PLAN.name}⁩` });
      await answerPlansReload([MANUAL_PLAN]);
      expect(store.plans()).toEqual([MANUAL_PLAN]);
    });

    it('says why a plan could not be deleted, and keeps it', async () => {
      await openWith();

      const removing = store.removePlan(PLAN);
      http
        .expectOne(`/api/backups/plans/${PLAN.id}/`)
        .flush({ error: { code: 'not_found', message: 'Server prose' } }, { status: 404, statusText: 'Not Found' });

      await expect(removing).resolves.toBe(false);
      expect(lastToast()).toEqual({ severity: 'danger', summary: 'This no longer exists.' });
      expect(store.plans()).toEqual([PLAN]);
    });
  });

  describe('running a plan', () => {
    it('marks the plan busy, then reloads the plans and the files and names the plan', async () => {
      await openWith({ plans: [PLAN, MANUAL_PLAN] });

      store.run(PLAN);
      expect(store.isRunning(PLAN)).toBe(true);
      expect(store.isRunning(MANUAL_PLAN)).toBe(false);
      expect(store.backingUp()).toBe(true);
      expect(store.taking()).toBe(false);
      const request = http.expectOne(`/api/backups/plans/${PLAN.id}/run/`);
      expect(request.request.method).toBe('POST');
      request.flush({ activity: JOB_ID }, { status: 202, statusText: 'Accepted' });

      jobs.report(jobOf('backup.run', { status: 'running', finished_at: null }));
      expect(store.isRunning(PLAN)).toBe(true);

      jobs.report(jobOf('backup.run'));
      expect(store.isRunning(PLAN)).toBe(false);
      expect(store.backingUp()).toBe(false);
      expect(lastToast()).toEqual({ severity: 'success', summary: 'Backup finished.', detail: `⁨${PLAN.name}⁩` });
      TestBed.tick();
      plansRequest().flush(pageOf([PLAN, MANUAL_PLAN]));
      listRequest().flush(pageOf([VERIFIED, FILE]));
      await settle();
      expect(store.files()).toEqual([VERIFIED, FILE]);
    });

    it('warns, naming the plan, when files changed while its archive was made', async () => {
      await openWith({ files: [FILE], plans: [ARCHIVE_PLAN] });

      store.run(ARCHIVE_PLAN);
      http.expectOne(`/api/backups/plans/${ARCHIVE_PLAN.id}/run/`).flush({ activity: JOB_ID });
      jobs.report(jobOf('backup.run', { detail: { plan: ARCHIVE_PLAN.id, warning: 'files_changed' } }));

      expect(store.isRunning(ARCHIVE_PLAN)).toBe(false);
      expect(lastToast()).toEqual({
        severity: 'warning',
        summary: 'Backup finished. Some files changed while they were archived.',
        detail: `⁨${ARCHIVE_PLAN.name}⁩`,
      });
      TestBed.tick();
      plansRequest().flush(pageOf([ARCHIVE_PLAN]));
      await answerReload([ARCHIVE_FILE, FILE]);
      expect(store.files()).toEqual([ARCHIVE_FILE, FILE]);
    });

    it("says why an archive was not kept, by its code", async () => {
      await openWith({ plans: [ARCHIVE_PLAN] });
      store.run(ARCHIVE_PLAN);
      http.expectOne(`/api/backups/plans/${ARCHIVE_PLAN.id}/run/`).flush({ activity: JOB_ID });

      jobs.report(jobOf('backup.run', { status: 'failed', error_code: 'archive_mismatch' }));

      expect(lastToast()).toEqual({
        severity: 'danger',
        summary: 'The archive fetched here does not match the one on the server. Nothing was kept.',
        detail: `⁨${ARCHIVE_PLAN.name}⁩`,
      });
      TestBed.tick();
      plansRequest().flush(pageOf([{ ...ARCHIVE_PLAN, last_status: 'failed', last_error_code: 'archive_mismatch' }]));
      await answerReload();
    });

    describe('a collection', () => {
      const collect = async (detail: Record<string, unknown>): Promise<void> => {
        await openWith({ files: [FILE], plans: [COLLECT_PLAN] });
        store.run(COLLECT_PLAN);
        http.expectOne(`/api/backups/plans/${COLLECT_PLAN.id}/run/`).flush({ activity: JOB_ID });
        jobs.report(jobOf('backup.run', { detail: { plan: COLLECT_PLAN.id, ...detail } }));
        expect(store.isRunning(COLLECT_PLAN)).toBe(false);
      };

      const answerReloads = async (): Promise<void> => {
        TestBed.tick();
        plansRequest().flush(pageOf([COLLECT_PLAN]));
        await answerReload([COLLECTED_FILE, FILE]);
      };

      it('says how many files it collected and how many it skipped, naming the plan', async () => {
        await collect({ collected: 2, skipped: 3, size: 4_096 });

        expect(lastToast()).toEqual({
          severity: 'success',
          summary: 'Collected: 2. Skipped: 3.',
          detail: `⁨${COLLECT_PLAN.name}⁩`,
        });
        await answerReloads();
        expect(store.files()).toEqual([COLLECTED_FILE, FILE]);
      });

      it('leaves out the skipped files when there were none', async () => {
        await collect({ collected: 1, skipped: 0, size: 2_048 });

        expect(lastToast()?.summary).toBe('Collected: 1.');
        await answerReloads();
      });

      it('finishes calmly when there was nothing new', async () => {
        await collect({ collected: 0, skipped: 3, size: 0 });

        expect(lastToast()).toEqual({
          severity: 'success',
          summary: 'Nothing new to collect.',
          detail: `⁨${COLLECT_PLAN.name}⁩`,
        });
        await answerReloads();
      });

      it('says, in Arabic too, how many it collected without a count before a noun', async () => {
        TestBed.inject(LocaleStore).setLocale('ar');
        await collect({ collected: 2, skipped: 3, size: 4_096 });

        expect(lastToast()?.summary).toBe('عدد الملفات التي تم جمعها: 2. عدد الملفات التي تم تخطيها: 3.');
        await answerReloads();
      });

      it('says when its folder is not on the server, or cannot be read', async () => {
        await openWith({ plans: [COLLECT_PLAN] });
        store.run(COLLECT_PLAN);
        http.expectOne(`/api/backups/plans/${COLLECT_PLAN.id}/run/`).flush({ activity: JOB_ID });

        jobs.report(jobOf('backup.run', { status: 'failed', error_code: 'remote_not_found' }));
        expect(lastToast()).toEqual({
          severity: 'danger',
          summary: 'The folder or file does not exist on the server.',
          detail: `⁨${COLLECT_PLAN.name}⁩`,
        });
        await answerReloads();

        store.run(COLLECT_PLAN);
        http.expectOne(`/api/backups/plans/${COLLECT_PLAN.id}/run/`).flush({ activity: OTHER_JOB });
        jobs.report(jobOf('backup.run', { id: OTHER_JOB, status: 'failed', error_code: 'remote_permission_denied' }));
        expect(lastToast()?.summary).toBe('Access to the folder or file was denied on the server.');
        await answerReloads();
      });
    });

    it('runs a plan once at a time', async () => {
      await openWith();

      store.run(PLAN);
      store.run(PLAN);

      http.expectOne(`/api/backups/plans/${PLAN.id}/run/`).flush({ activity: JOB_ID });
      expect(jobs.watched).toEqual([JOB_ID]);
      jobs.report(jobOf('backup.run'));
      TestBed.tick();
      plansRequest().flush(pageOf([PLAN]));
      await answerReload();
    });

    it('says why the run failed, by its code, and which plan it was', async () => {
      await openWith();
      store.run(PLAN);
      http.expectOne(`/api/backups/plans/${PLAN.id}/run/`).flush({ activity: JOB_ID });

      jobs.report(jobOf('backup.run', { status: 'failed', error_code: 'ssh_unreachable' }));

      expect(lastToast()).toEqual({
        severity: 'danger',
        summary: 'The server did not answer over SSH.',
        detail: `⁨${PLAN.name}⁩`,
      });
      TestBed.tick();
      plansRequest().flush(pageOf([{ ...PLAN, last_status: 'failed', last_error_code: 'ssh_unreachable' }]));
      await answerReload();
      expect(store.plans()[0].last_status).toBe('failed');
    });

    it('says a backup is already running when the backend refuses another', async () => {
      await openWith();
      store.run(PLAN);
      http
        .expectOne(`/api/backups/plans/${PLAN.id}/run/`)
        .flush({ error: { code: 'backup_running', message: 'Server prose' } }, { status: 409, statusText: 'Conflict' });

      expect(store.isRunning(PLAN)).toBe(false);
      expect(jobs.watched).toEqual([]);
      expect(lastToast()).toEqual({
        severity: 'danger',
        summary: 'A backup or restore of this server is already running.',
        detail: `⁨${PLAN.name}⁩`,
      });
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
      expect(request.request.body).toEqual({ server: SERVER_ID });
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

    it('takes one backup of a server at a time, and shows it only on that server', async () => {
      await openWith();
      store.take();
      store.take();
      http.expectOne('/api/backups/take/').flush({ activity: JOB_ID });

      await openWith({ files: [], plans: [] }, OTHER_SERVER);
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
      expect(lastToast()).toEqual({ severity: 'danger', summary: 'A backup or restore of this server is already running.' });
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
      expect((request.request.body as FormData).get('server')).toBe(SERVER_ID);

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
      expect(lastToast()).toEqual({
        severity: 'success',
        summary: 'Backup uploaded.',
        detail: `⁨${UPLOADED_FILE.name}⁩`,
      });
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

    it('uploads one file to a server at a time, and shows it only on that server', async () => {
      await openWith();
      store.uploadFile(chosen());
      store.uploadFile(chosen());
      const request = uploadRequest();

      await openWith({ files: [], plans: [] }, OTHER_SERVER);
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
      expect(lastToast()).toEqual({
        severity: 'success',
        summary: 'Check passed.',
        detail: `⁨${FILE.name}⁩`,
      });
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
      server_name: 'production-web',
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

      jobs.report(restored({ records: 1, files: 0, copy_left: '/var/backups/.dbs-interface-restore-ab.dbs' }));

      expect(lastToast()).toEqual({
        severity: 'warning',
        summary: 'Rehearsal finished. Nothing changed.',
        detail: 'Records: 1. Files: 0. The copy sent to the server is still at ⁨/var/backups/.dbs-interface-restore-ab.dbs⁩.',
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
        summary: 'django-dbs on the server is too old for this. It needs version 0.2.2 or later.',
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
    });
  });

  describe('jobs already running when the page opens', () => {
    const run: UnfinishedJob = {
      id: JOB_ID,
      action: 'backup.run',
      status: 'running',
      target: PLAN.name,
      detail: { plan: PLAN.id },
    };
    const take: UnfinishedJob = {
      id: OTHER_JOB,
      action: 'backup.take',
      status: 'queued',
      target: 'Production web',
      detail: {},
    };
    const check: UnfinishedJob = {
      id: THIRD_JOB,
      action: 'backup.verify',
      status: 'queued',
      target: FILE.name,
      detail: {},
    };

    it('follows every backup and check of the server, with their busy state and their toasts', async () => {
      await openWith({
        files: [FILE],
        plans: [PLAN, MANUAL_PLAN],
        running: [run],
        queued: [take, check, { id: 'other', action: 'server.check', status: 'queued', target: 'Production web', detail: {} }],
      });

      expect(jobs.watched).toEqual([JOB_ID, OTHER_JOB, THIRD_JOB]);
      expect(store.isRunning(PLAN)).toBe(true);
      expect(store.isRunning(MANUAL_PLAN)).toBe(false);
      expect(store.taking()).toBe(true);
      expect(store.isVerifying(FILE)).toBe(true);

      jobs.report(jobOf('backup.run'));
      expect(store.isRunning(PLAN)).toBe(false);
      expect(lastToast()).toEqual({ severity: 'success', summary: 'Backup finished.', detail: `⁨${PLAN.name}⁩` });
      TestBed.tick();
      plansRequest().flush(pageOf([PLAN, MANUAL_PLAN]));
      await answerReload();

      jobs.report(jobOf('backup.verify', { id: THIRD_JOB, detail: { validation: 'verified' } }));
      expect(store.isVerifying(FILE)).toBe(false);
      expect(lastToast()).toEqual({ severity: 'success', summary: 'Check passed.', detail: `⁨${FILE.name}⁩` });
      await answerReload();

      jobs.report(jobOf('backup.take', { id: OTHER_JOB, status: 'failed', error_code: 'interrupted' }));
      expect(store.taking()).toBe(false);
      expect(lastToast()).toEqual({ severity: 'danger', summary: 'The job stopped before it finished.' });
      await answerReload();
    });

    it('follows a restore picked up on open, rehearsal or not', async () => {
      const restore: UnfinishedJob = {
        id: JOB_ID,
        action: 'backup.restore',
        status: 'running',
        target: FILE.name,
        detail: { backup: FILE.id, mode: 'replace', rehearse: false },
      };
      await openWith({ files: [FILE], running: [restore] });

      expect(store.restoring(FILE)).toBe('restore');

      jobs.report(
        jobOf('backup.restore', {
          detail: { ...restore.detail, records: 5, files: 1, flushed: 2, healed: false },
        }),
      );
      expect(store.restoring(FILE)).toBeNull();
      expect(lastToast()).toEqual({
        severity: 'success',
        summary: 'Backup restored.',
        detail: 'Records: 5. Files: 1. Records cleared first: 2.',
      });
    });

    it("finds a run's plan by id, so a plan renamed since is still the one marked busy", async () => {
      const renamed: BackupPlan = { ...PLAN, name: 'Nightly' };
      await openWith({ plans: [renamed, MANUAL_PLAN], running: [run] });

      expect(store.isRunning(renamed)).toBe(true);
      expect(store.isRunning({ ...MANUAL_PLAN, name: PLAN.name })).toBe(false);

      jobs.report(jobOf('backup.run'));
      expect(store.isRunning(renamed)).toBe(false);
      TestBed.tick();
      plansRequest().flush(pageOf([renamed, MANUAL_PLAN]));
      await answerReload();
    });

    it('leaves a run alone when its entry names no plan', async () => {
      await openWith({ running: [{ ...run, detail: {} }] });

      expect(jobs.watched).toEqual([]);
      expect(store.backingUp()).toBe(false);
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
      store.open(SERVER_ID);
      TestBed.tick();
      listRequest().flush(pageOf([FILE]));
      plansRequest().flush(pageOf([PLAN]));
      jobsRequest('running').flush(
        { error: { code: 'unknown', message: 'Server prose' } },
        { status: 500, statusText: 'Server Error' },
      );
      expect(jobsRequest('queued').cancelled).toBe(true);
      await settle();

      expect(jobs.watched).toEqual([]);
      expect(toasts).not.toHaveBeenCalled();
      expect(store.files()).toEqual([FILE]);
      expect(store.plans()).toEqual([PLAN]);
    });
  });

  describe('deleting a backup', () => {
    it('deletes it, reloads the list, and offers Undo on the server it was on', async () => {
      await openWith({ files: [FILE, VERIFIED] });

      const removing = store.remove(FILE);
      expect(store.deleting().has(FILE.id)).toBe(true);
      http.expectOne(`/api/backups/${FILE.id}/`).flush(null, { status: 204, statusText: 'No Content' });

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

      const removing = store.remove(FILE);
      http.expectOne(`/api/backups/${FILE.id}/`).flush(null, { status: 204, statusText: 'No Content' });
      await removing;
      await answerReload([]);

      store.dismissDeleted();
      expect(store.deleted()).toBeNull();
    });

    it('says why it could not be deleted, and keeps the row', async () => {
      await openWith({ files: [FILE] });

      const removing = store.remove(FILE);
      http
        .expectOne(`/api/backups/${FILE.id}/`)
        .flush({ error: { code: 'not_found', message: 'Server prose' } }, { status: 404, statusText: 'Not Found' });

      await expect(removing).resolves.toBe(false);
      expect(store.deleting().has(FILE.id)).toBe(false);
      expect(lastToast()).toEqual({ severity: 'danger', summary: 'This no longer exists.' });
      expect(store.files()).toEqual([FILE]);
    });
  });

  it('points a download at the file', () => {
    expect(store.downloadUrl(FILE)).toBe(`/api/backups/${FILE.id}/download/`);
  });

  function answerPlansAndJobsExceptPlans(): void {
    jobsRequest('running').flush(pageOf([]));
    jobsRequest('queued').flush(pageOf([]));
  }
});
