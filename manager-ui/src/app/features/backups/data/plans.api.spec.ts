import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { APPLICATION_ID, ARCHIVE_PLAN, JOB_ID, PLAN, pageOf, unfinished } from '../testing/backups.fixtures';
import { PlansApi } from './plans.api';

describe('PlansApi', () => {
  let api: PlansApi;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(PlansApi);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
  });

  it("lists one application's plans a page at a time", async () => {
    const listing = firstValueFrom(api.list({ application: APPLICATION_ID, page: 1, page_size: 20 }));
    const request = http.expectOne(`/api/backups/plans/?application=${APPLICATION_ID}&page=1&page_size=20`);
    expect(request.request.method).toBe('GET');
    request.flush(pageOf([PLAN]));

    await expect(listing).resolves.toEqual(pageOf([PLAN]));
  });

  it('adds a plan to an application, with its first run and time zone', async () => {
    const plan = {
      application: APPLICATION_ID,
      kind: 'dbs',
      name: PLAN.name,
      interval_minutes: 1440,
      keep: 5,
      keep_remote: 1,
      enabled: true,
      paths: [],
      pattern: '',
      time_zone: 'Europe/Berlin',
      anchor_at: '2026-10-20T02:30:00+02:00',
    } as const;
    const creating = firstValueFrom(api.create(plan));
    const request = http.expectOne('/api/backups/plans/');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual(plan);
    request.flush(PLAN, { status: 201, statusText: 'Created' });

    await expect(creating).resolves.toEqual(PLAN);
  });

  it('changes only what it is given', async () => {
    const updating = firstValueFrom(api.update(ARCHIVE_PLAN.id, { paths: ['/srv/app/media'] }));
    const request = http.expectOne(`/api/backups/plans/${ARCHIVE_PLAN.id}/`);
    expect(request.request.method).toBe('PATCH');
    expect(request.request.body).toEqual({ paths: ['/srv/app/media'] });
    request.flush({ ...ARCHIVE_PLAN, paths: ['/srv/app/media'] });

    await expect(updating).resolves.toEqual({ ...ARCHIVE_PLAN, paths: ['/srv/app/media'] });
  });

  it('deletes a plan', async () => {
    const removing = firstValueFrom(api.remove(PLAN.id));
    const request = http.expectOne(`/api/backups/plans/${PLAN.id}/`);
    expect(request.request.method).toBe('DELETE');
    request.flush(null, { status: 204, statusText: 'No Content' });

    await expect(removing).resolves.toBeNull();
  });

  it('starts a run of a plan and answers with its job', async () => {
    const running = firstValueFrom(api.run(PLAN.id));
    const request = http.expectOne(`/api/backups/plans/${PLAN.id}/run/`);
    expect(request.request.method).toBe('POST');
    request.flush({ activity: JOB_ID }, { status: 202, statusText: 'Accepted' });

    await expect(running).resolves.toEqual({ activity: JOB_ID });
  });

  it('pauses and resumes a plan', async () => {
    const pausing = firstValueFrom(api.pause(PLAN.id));
    const pause = http.expectOne(`/api/backups/plans/${PLAN.id}/pause/`);
    expect(pause.request.method).toBe('POST');
    expect(pause.request.body).toEqual({});
    pause.flush({ ...PLAN, enabled: false, next_run_at: null });
    await expect(pausing).resolves.toEqual({ ...PLAN, enabled: false, next_run_at: null });

    const resuming = firstValueFrom(api.resume(PLAN.id));
    const resume = http.expectOne(`/api/backups/plans/${PLAN.id}/resume/`);
    expect(resume.request.method).toBe('POST');
    expect(resume.request.body).toEqual({});
    resume.flush(PLAN);
    await expect(resuming).resolves.toEqual(PLAN);
  });

  it('moves the next run of a plan', async () => {
    const moving = firstValueFrom(api.reschedule(PLAN.id, { next_run_at: '2026-10-21T03:00:00+00:00' }));
    const request = http.expectOne(`/api/backups/plans/${PLAN.id}/reschedule/`);
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ next_run_at: '2026-10-21T03:00:00+00:00' });
    request.flush({ ...PLAN, next_run_at: '2026-10-21T03:00:00Z' });

    await expect(moving).resolves.toEqual({ ...PLAN, next_run_at: '2026-10-21T03:00:00Z' });
  });

  it("reads an application's unfinished plan runs in one status", async () => {
    const run = unfinished('backup.run', { target: PLAN.name, detail: { plan: PLAN.id } });
    const reading = firstValueFrom(api.unfinishedRuns(APPLICATION_ID, 'queued'));
    const request = http.expectOne(
      `/api/activity/?application=${APPLICATION_ID}&action=backup.run&status=queued&page=1&page_size=100`,
    );
    expect(request.request.method).toBe('GET');
    request.flush(pageOf([run]));

    await expect(reading).resolves.toEqual(pageOf([run]));
  });
});
