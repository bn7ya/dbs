import { provideHttpClient, withInterceptors } from '@angular/common/http';
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
import type { BackupPlan, PlanSettings } from '../data/plans.types';
import en from '../i18n/en.json';
import ar from '../i18n/ar.json';
import {
  APPLICATION_ID,
  ARCHIVE_PLAN,
  COLLECT_PLAN,
  JOB_ID,
  MANUAL_PLAN,
  OTHER_APPLICATION_ID,
  PAUSED_PLAN,
  PLAN,
  jobOf,
  pageOf,
  unfinished,
} from '../testing/backups.fixtures';
import type { PlansOpening } from '../testing/backups.fixtures.types';
import { PlansStore } from './plans.store';

const OTHER_JOB = 10;

const SETTINGS: PlanSettings = {
  name: 'django-dbs',
  interval_minutes: 1440,
  keep: 5,
  keep_remote: 1,
  enabled: true,
  paths: [],
  pattern: '',
  time_zone: 'Europe/Berlin',
};

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

describe('PlansStore', () => {
  let store: PlansStore;
  let http: HttpTestingController;
  let jobs: FakeJobWatcher;
  let toasts: MockInstance<(message: ToastMessage) => void>;

  const plansRequest = (): TestRequest =>
    http.expectOne((request) => request.url === '/api/backups/plans/' && request.method === 'GET');
  const runsRequest = (status: string): TestRequest =>
    http.expectOne((request) => request.url === '/api/activity/' && request.params.get('status') === status);

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const openWith = async (
    { plans = [PLAN], running = [], queued = [] }: PlansOpening = {},
    application = APPLICATION_ID,
  ): Promise<void> => {
    store.open(application);
    TestBed.tick();
    plansRequest().flush(pageOf(plans));
    runsRequest('running').flush(pageOf(running));
    runsRequest('queued').flush(pageOf(queued));
    await settle();
  };

  const answerReload = async (results: readonly BackupPlan[] = [PLAN]): Promise<void> => {
    TestBed.tick();
    plansRequest().flush(pageOf(results));
    await settle();
  };

  const lastToast = (): ToastMessage | undefined => toasts.mock.lastCall?.[0];

  const refused = (code: string, fields?: Record<string, string[]>) =>
    [{ error: { code, message: 'Server prose', ...(fields ? { fields } : {}) } }, { status: 400, statusText: 'Bad Request' }] as const;

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [
        PlansStore,
        { provide: JobWatcher, useClass: FakeJobWatcher },
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    TestBed.inject(LocaleStore).register({ en, ar });
    store = TestBed.inject(PlansStore);
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

  describe('the plans', () => {
    it('loads nothing until the page opens it', () => {
      TestBed.tick();

      http.expectNone(() => true);
      expect(store.plans()).toEqual([]);
      expect(store.pending()).toBe(false);
    });

    it("lists the application's plans a page at a time", async () => {
      store.open(APPLICATION_ID);
      TestBed.tick();
      expect(store.pending()).toBe(true);
      const request = plansRequest();
      expect(request.request.params.get('application')).toBe(APPLICATION_ID);
      expect(request.request.params.get('page')).toBe('1');
      expect(request.request.params.get('page_size')).toBe('20');
      request.flush(pageOf([PLAN, MANUAL_PLAN], 21));
      runsRequest('running').flush(pageOf([]));
      runsRequest('queued').flush(pageOf([]));
      await settle();

      expect(store.plans()).toEqual([PLAN, MANUAL_PLAN]);
      expect(store.count()).toBe(21);
      expect(store.empty()).toBe(false);

      store.goToPage(1);
      TestBed.tick();
      const next = plansRequest();
      expect(next.request.params.get('page')).toBe('2');
      expect(store.plans()).toEqual([PLAN, MANUAL_PLAN]);
      next.flush(pageOf([MANUAL_PLAN], 21));
      await settle();
      expect(store.plans()).toEqual([MANUAL_PLAN]);
    });

    it("never shows one application's plans on another's tab", async () => {
      await openWith();

      store.open(OTHER_APPLICATION_ID);
      TestBed.tick();
      expect(store.plans()).toEqual([]);
      expect(store.pending()).toBe(true);
      await answerReloadAndRuns([]);
      expect(store.empty()).toBe(true);
    });

    it('holds a failure to list them, and retries', async () => {
      store.open(APPLICATION_ID);
      TestBed.tick();
      plansRequest().flush({ error: { code: 'unknown', message: 'Server prose' } }, { status: 500, statusText: 'Error' });
      runsRequest('running').flush(pageOf([]));
      runsRequest('queued').flush(pageOf([]));
      await settle();
      expect(store.error()?.code).toBe('unknown');

      store.reload();
      await answerReload();
      expect(store.error()).toBeNull();
      expect(store.plans()).toEqual([PLAN]);
    });

    it('forgets the rows when the page closes', async () => {
      await openWith();

      store.close();
      TestBed.tick();

      expect(store.plans()).toEqual([]);
    });
  });

  describe('saving a plan', () => {
    it('adds a plan to the application on screen, with its time zone, then reloads and says so', async () => {
      await openWith({ plans: [] });

      const creating = store.createPlan('dbs', { ...SETTINGS, anchor_at: '2026-10-20T02:30:00+02:00' });
      expect(store.saving()).toBe(true);
      const request = http.expectOne((each) => each.url === '/api/backups/plans/' && each.method === 'POST');
      expect(request.request.body).toEqual({
        ...SETTINGS,
        anchor_at: '2026-10-20T02:30:00+02:00',
        application: APPLICATION_ID,
        kind: 'dbs',
      });
      request.flush(PLAN, { status: 201, statusText: 'Created' });

      await expect(creating).resolves.toEqual(PLAN);
      expect(store.saving()).toBe(false);
      expect(lastToast()).toEqual({ severity: 'success', summary: 'Plan added.', detail: `⁨${PLAN.name}⁩` });
      await answerReload([PLAN]);
    });

    it('adds a plan that reads the server with the password', async () => {
      await openWith({ plans: [] });

      const settings = { ...SETTINGS, name: 'Media', paths: ARCHIVE_PLAN.paths };
      const creating = store.createPlan('archive', settings, { account_password: 'hunter2' });
      const request = http.expectOne((each) => each.url === '/api/backups/plans/' && each.method === 'POST');
      expect(request.request.body).toEqual({
        ...settings,
        account_password: 'hunter2',
        application: APPLICATION_ID,
        kind: 'archive',
      });
      request.flush(ARCHIVE_PLAN, { status: 201, statusText: 'Created' });
      await creating;
      await answerReload([ARCHIVE_PLAN]);
    });

    it('holds what the backend refused, field by field, until the form opens again', async () => {
      await openWith();

      const creating = store.createPlan('dbs', SETTINGS);
      http
        .expectOne((each) => each.url === '/api/backups/plans/' && each.method === 'POST')
        .flush(...refused('invalid', { time_zone: ['invalid_time_zone'] }));

      await expect(creating).resolves.toBeNull();
      expect(store.saveError()?.fields).toEqual({ time_zone: ['invalid_time_zone'] });
      expect(toasts).not.toHaveBeenCalled();

      store.resetPlanForm();
      expect(store.saveError()).toBeNull();
    });

    it("saves a plan's settings", async () => {
      await openWith();

      const changed = { ...SETTINGS, keep: 4 };
      const updating = store.updatePlan(PLAN, changed, { account_password: 'hunter2' });
      const request = http.expectOne(`/api/backups/plans/${PLAN.id}/`);
      expect(request.request.method).toBe('PATCH');
      expect(request.request.body).toEqual({ ...changed, account_password: 'hunter2' });
      request.flush({ ...PLAN, keep: 4 });

      await expect(updating).resolves.toEqual({ ...PLAN, keep: 4 });
      expect(lastToast()).toEqual({ severity: 'success', summary: 'Plan saved.', detail: `⁨${PLAN.name}⁩` });
      await answerReload([{ ...PLAN, keep: 4 }]);
    });

    it('deletes a plan, then reloads the plans and says so', async () => {
      await openWith({ plans: [PLAN, MANUAL_PLAN] });

      const removing = store.removePlan(PLAN);
      expect(store.deleting().has(PLAN.id)).toBe(true);
      http.expectOne(`/api/backups/plans/${PLAN.id}/`).flush(null, { status: 204, statusText: 'No Content' });

      await expect(removing).resolves.toBe(true);
      expect(store.deleting().has(PLAN.id)).toBe(false);
      expect(lastToast()).toEqual({ severity: 'success', summary: 'Plan deleted.', detail: `⁨${PLAN.name}⁩` });
      await answerReload([MANUAL_PLAN]);
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

  describe('pausing and resuming', () => {
    it('pauses a plan, marks it busy meanwhile, then reloads and says so', async () => {
      await openWith();

      const pausing = store.pause(PLAN);
      expect(store.isChanging(PLAN)).toBe(true);
      const request = http.expectOne(`/api/backups/plans/${PLAN.id}/pause/`);
      expect(request.request.method).toBe('POST');
      request.flush({ ...PLAN, enabled: false, next_run_at: null });

      await expect(pausing).resolves.toBe(true);
      expect(store.isChanging(PLAN)).toBe(false);
      expect(lastToast()).toEqual({
        severity: 'success',
        summary: 'Plan paused. It runs only from Run now until it is resumed.',
        detail: `⁨${PLAN.name}⁩`,
      });
      await answerReload([{ ...PLAN, enabled: false, next_run_at: null }]);
    });

    it('resumes a plan, saying missed runs are not made up', async () => {
      await openWith({ plans: [PAUSED_PLAN] });

      const resuming = store.resume(PAUSED_PLAN);
      http.expectOne(`/api/backups/plans/${PAUSED_PLAN.id}/resume/`).flush({ ...PAUSED_PLAN, enabled: true });

      await expect(resuming).resolves.toBe(true);
      expect(lastToast()?.summary).toBe(
        'Plan resumed. It runs at its next time after now; runs missed while it was paused are not made up.',
      );
      await answerReload([{ ...PAUSED_PLAN, enabled: true }]);
    });

    it('says a manual plan cannot be paused, and changes nothing', async () => {
      await openWith({ plans: [MANUAL_PLAN] });

      const pausing = store.pause(MANUAL_PLAN);
      http
        .expectOne(`/api/backups/plans/${MANUAL_PLAN.id}/pause/`)
        .flush(...refused('invalid', { interval_minutes: ['manual_plan'] }));

      await expect(pausing).resolves.toBe(false);
      expect(lastToast()).toEqual({ severity: 'danger', summary: 'This plan runs only from Run now. Give it a schedule first.', detail: `⁨${MANUAL_PLAN.name}⁩` });
    });
  });

  describe('rescheduling', () => {
    it('moves the next run, then reloads and says so', async () => {
      await openWith();

      const moving = store.reschedule(PLAN, '2026-10-21T03:00:00+02:00');
      expect(store.rescheduling()).toBe(true);
      const request = http.expectOne(`/api/backups/plans/${PLAN.id}/reschedule/`);
      expect(request.request.body).toEqual({ next_run_at: '2026-10-21T03:00:00+02:00' });
      request.flush({ ...PLAN, next_run_at: '2026-10-21T01:00:00Z' });

      await expect(moving).resolves.toEqual({ ...PLAN, next_run_at: '2026-10-21T01:00:00Z' });
      expect(store.rescheduling()).toBe(false);
      expect(lastToast()).toEqual({ severity: 'success', summary: 'Plan rescheduled.', detail: `⁨${PLAN.name}⁩` });
      await answerReload();
    });

    it('keeps a refused moment for the form', async () => {
      await openWith();

      const moving = store.reschedule(PLAN, '2020-01-01T00:00:00+00:00');
      http
        .expectOne(`/api/backups/plans/${PLAN.id}/reschedule/`)
        .flush(...refused('invalid', { next_run_at: ['invalid_moment'] }));

      await expect(moving).resolves.toBeNull();
      expect(store.rescheduleError()?.fields).toEqual({ next_run_at: ['invalid_moment'] });
      expect(toasts).not.toHaveBeenCalled();

      store.resetRescheduleForm();
      expect(store.rescheduleError()).toBeNull();
    });
  });

  describe('running a plan', () => {
    it('marks the plan busy, then reloads the plans and names the plan', async () => {
      await openWith({ plans: [PLAN, MANUAL_PLAN] });

      store.run(PLAN);
      expect(store.isRunning(PLAN)).toBe(true);
      expect(store.isRunning(MANUAL_PLAN)).toBe(false);
      expect(store.running()).toBe(true);
      const request = http.expectOne(`/api/backups/plans/${PLAN.id}/run/`);
      expect(request.request.method).toBe('POST');
      request.flush({ activity: JOB_ID }, { status: 202, statusText: 'Accepted' });

      const connection = { state: 'lost', last_activity_at: '2026-09-30T12:00:30Z', bytes: 4096 } as const;
      jobs.report(jobOf('backup.run', { status: 'running', finished_at: null, connection }));
      expect(store.isRunning(PLAN)).toBe(true);
      expect(store.liveConnection()).toEqual(connection);

      jobs.report(jobOf('backup.run', { detail: { plan: PLAN.id, backup: 'b1' } }));
      expect(store.isRunning(PLAN)).toBe(false);
      expect(store.running()).toBe(false);
      expect(store.liveConnection()).toBeNull();
      expect(lastToast()).toEqual({ severity: 'success', summary: 'Backup finished.', detail: `⁨${PLAN.name}⁩` });
      await answerReload([PLAN, MANUAL_PLAN]);
    });

    it('warns, naming the plan, when its backup was left on the server', async () => {
      await openWith();
      store.run(PLAN);
      http.expectOne(`/api/backups/plans/${PLAN.id}/run/`).flush({ activity: JOB_ID });

      jobs.report(jobOf('backup.run', { detail: { plan: PLAN.id, outcome: 'kept_on_server', pulled: 0 } }));

      expect(lastToast()).toEqual({
        severity: 'warning',
        summary:
          'The connection broke before the backup arrived. The server keeps it, and the manager collects it at the next connection.',
        detail: `⁨${PLAN.name}⁩`,
      });
      await answerReload();
    });

    it('warns when files changed while its archive was made', async () => {
      await openWith({ plans: [ARCHIVE_PLAN] });
      store.run(ARCHIVE_PLAN);
      http.expectOne(`/api/backups/plans/${ARCHIVE_PLAN.id}/run/`).flush({ activity: JOB_ID });

      jobs.report(jobOf('backup.run', { detail: { plan: ARCHIVE_PLAN.id, warning: 'files_changed' } }));

      expect(lastToast()).toEqual({
        severity: 'warning',
        summary: 'Backup finished. Some files changed while they were archived.',
        detail: `⁨${ARCHIVE_PLAN.name}⁩`,
      });
      await answerReload([ARCHIVE_PLAN]);
    });

    describe('a collection', () => {
      const collect = async (detail: Record<string, unknown>): Promise<void> => {
        await openWith({ plans: [COLLECT_PLAN] });
        store.run(COLLECT_PLAN);
        http.expectOne(`/api/backups/plans/${COLLECT_PLAN.id}/run/`).flush({ activity: JOB_ID });
        jobs.report(jobOf('backup.run', { detail: { plan: COLLECT_PLAN.id, ...detail } }));
        await answerReload([COLLECT_PLAN]);
      };

      it('says how many files it collected and how many it skipped, naming the plan', async () => {
        await collect({ collected: 2, skipped: 3, size: 4_096 });

        expect(lastToast()).toEqual({
          severity: 'success',
          summary: 'Collected: 2. Skipped: 3.',
          detail: `⁨${COLLECT_PLAN.name}⁩`,
        });
      });

      it('leaves out the skipped files when there were none', async () => {
        await collect({ collected: 1, skipped: 0, size: 2_048 });

        expect(lastToast()?.summary).toBe('Collected: 1.');
      });

      it('finishes calmly when there was nothing new', async () => {
        await collect({ collected: 0, skipped: 3, size: 0 });

        expect(lastToast()?.summary).toBe('Nothing new to collect.');
      });

      it('says, in Arabic too, how many it collected without a count before a noun', async () => {
        TestBed.inject(LocaleStore).setLocale('ar');
        await collect({ collected: 2, skipped: 3, size: 4_096 });

        expect(lastToast()?.summary).toBe('عدد الملفات التي تم جمعها: 2. عدد الملفات التي تم تخطيها: 3.');
      });
    });

    it('runs a plan once at a time', async () => {
      await openWith();

      store.run(PLAN);
      store.run(PLAN);

      http.expectOne(`/api/backups/plans/${PLAN.id}/run/`).flush({ activity: JOB_ID });
      expect(jobs.watched).toEqual([JOB_ID]);
      jobs.report(jobOf('backup.run'));
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
      await answerReload([{ ...PLAN, last_status: 'failed', last_error_code: 'ssh_unreachable' }]);
      expect(store.plans()[0].last_status).toBe('failed');
    });

    it('marks nothing busy when the backend refuses the run', async () => {
      await openWith();
      store.run(PLAN);
      http
        .expectOne(`/api/backups/plans/${PLAN.id}/run/`)
        .flush({ error: { code: 'backup_running', message: 'Server prose' } }, { status: 409, statusText: 'Conflict' });

      expect(store.isRunning(PLAN)).toBe(false);
      expect(jobs.watched).toEqual([]);
      expect(lastToast()?.severity).toBe('danger');
      expect(lastToast()?.detail).toBe(`⁨${PLAN.name}⁩`);
    });
  });

  describe('runs already going when the page opens', () => {
    const run = unfinished('backup.run', { target: PLAN.name, detail: { plan: PLAN.id } });

    it("follows them, finding each run's plan by id", async () => {
      const renamed: BackupPlan = { ...PLAN, name: 'Nightly' };
      await openWith({ plans: [renamed, MANUAL_PLAN], queued: [run] });

      expect(store.isRunning(renamed)).toBe(true);
      expect(store.isRunning({ ...MANUAL_PLAN, name: PLAN.name })).toBe(false);

      jobs.report(jobOf('backup.run'));
      expect(store.isRunning(renamed)).toBe(false);
      await answerReload([renamed, MANUAL_PLAN]);
    });

    it('asks only for the runs of the application on screen', async () => {
      store.open(APPLICATION_ID);
      TestBed.tick();
      plansRequest().flush(pageOf([PLAN]));
      const running = runsRequest('running');
      expect(running.request.params.get('application')).toBe(APPLICATION_ID);
      expect(running.request.params.get('action')).toBe('backup.run');
      running.flush(pageOf([]));
      runsRequest('queued').flush(pageOf([]));
      await settle();
    });

    it('leaves a run alone when its entry names no plan, and follows a run once', async () => {
      await openWith({ running: [{ ...run, detail: {} }] });
      expect(jobs.watched).toEqual([]);
      expect(store.running()).toBe(false);

      store.run(PLAN);
      http.expectOne(`/api/backups/plans/${PLAN.id}/run/`).flush({ activity: OTHER_JOB });
      store.close();
      TestBed.tick();
      await openWith({ running: [{ ...run, id: OTHER_JOB }] });
      expect(jobs.watched).toEqual([OTHER_JOB]);

      jobs.report(jobOf('backup.run', { id: OTHER_JOB }));
      expect(toasts).toHaveBeenCalledTimes(1);
      await answerReload();
    });

    it('leaves the page as it is when the runs cannot be read', async () => {
      store.open(APPLICATION_ID);
      TestBed.tick();
      plansRequest().flush(pageOf([PLAN]));
      runsRequest('running').flush({ error: { code: 'unknown', message: 'Server prose' } }, { status: 500, statusText: 'Error' });
      expect(runsRequest('queued').cancelled).toBe(true);
      await settle();

      expect(jobs.watched).toEqual([]);
      expect(toasts).not.toHaveBeenCalled();
      expect(store.plans()).toEqual([PLAN]);
    });
  });

  async function answerReloadAndRuns(plans: readonly BackupPlan[]): Promise<void> {
    plansRequest().flush(pageOf(plans));
    runsRequest('running').flush(pageOf([]));
    runsRequest('queued').flush(pageOf([]));
    await settle();
  }
});
