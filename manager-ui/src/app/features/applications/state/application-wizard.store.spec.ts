import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { JobWatcher } from '@core/jobs/job-watcher';
import type { Job } from '@core/jobs/job.types';
import { settingsOf, draftFromCandidate } from '../components/settings-fields/application-draft';
import { APPLICATION, CHECKED, COMPOSE_CANDIDATE, DISCOVERY, HOST, SERVER_ID } from '../testing/applications.fixtures';
import { ApplicationWizardStore } from './application-wizard.store';

const RUNNING: Job = {
  id: 7,
  action: 'backup.take',
  status: 'running',
  detail: {},
  error_code: '',
  finished_at: null,
  connection: { state: 'alive', last_activity_at: '2026-09-30T12:00:00Z', bytes: 1024 },
};

const DONE: Job = { ...RUNNING, status: 'succeeded', connection: null, finished_at: '2026-09-30T12:01:00Z' };

describe('ApplicationWizardStore', () => {
  let store: ApplicationWizardStore;
  let http: HttpTestingController;
  const watch = vi.fn(() => of(RUNNING, DONE));

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const open = async (): Promise<void> => {
    store.open(SERVER_ID);
    TestBed.tick();
    http.expectOne(`/api/servers/${SERVER_ID}/`).flush(HOST);
    await settle();
  };

  const created = async (): Promise<void> => {
    await open();
    const creating = store.create({ ...settingsOf(draftFromCandidate(COMPOSE_CANDIDATE)), discovered: true });
    http.expectOne('/api/applications/').flush(APPLICATION, { status: 201, statusText: 'Created' });
    await creating;
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        ApplicationWizardStore,
        { provide: JobWatcher, useValue: { watch } },
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    store = TestBed.inject(ApplicationWizardStore);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    watch.mockClear();
  });

  it('reads the server the application goes on', async () => {
    await open();

    expect(store.server()?.name).toBe('Production web');
  });

  it('discovers in a folder, or asks for suggestions without one, with the password when given', async () => {
    await open();

    const searching = store.discover('/srv/shop');
    expect(store.discovering()).toBe(true);
    const request = http.expectOne('/api/applications/discover/');
    expect(request.request.body).toEqual({ server: SERVER_ID, folder: '/srv/shop' });
    request.flush(DISCOVERY);
    await expect(searching).resolves.toEqual(DISCOVERY);
    expect(store.discovery()).toEqual(DISCOVERY);

    void store.discover('', 'hunter2');
    expect(http.expectOne('/api/applications/discover/').request.body).toEqual({ server: SERVER_ID, account_password: 'hunter2' });
  });

  it('keeps why discovery was refused, and the discovery before it', async () => {
    await open();
    const first = store.discover('/srv/shop');
    http.expectOne('/api/applications/discover/').flush(DISCOVERY);
    await first;

    const refused = store.discover('/srv/blog');
    http.expectOne('/api/applications/discover/').flush(
      { error: { code: 'invalid', message: 'Server prose', fields: { account_password: ['required'] } } },
      { status: 400, statusText: 'Bad Request' },
    );

    await expect(refused).resolves.toBeNull();
    expect(store.discoverError()?.fields?.['account_password']).toEqual(['required']);
    expect(store.discovery()).toEqual(DISCOVERY);
  });

  it('creates the application on the server, then checks it', async () => {
    await open();
    const creating = store.create({ ...settingsOf(draftFromCandidate(COMPOSE_CANDIDATE)), discovered: true });
    const post = http.expectOne('/api/applications/');
    expect(post.request.body).toMatchObject({ server: SERVER_ID, discovered: true, kind: 'compose', compose_service: 'web' });
    post.flush(APPLICATION, { status: 201, statusText: 'Created' });
    await creating;
    expect(store.application()?.id).toBe(APPLICATION.id);

    const checking = store.check();
    http.expectOne(`/api/applications/${APPLICATION.id}/check/`).flush(CHECKED);
    await expect(checking).resolves.toBe(true);
    expect(store.versions()?.compatible).toBe(true);
  });

  it('saves a change to the new application', async () => {
    await created();

    const saving = store.update({ python_path: '/app/venv/bin/python' });
    http.expectOne(`/api/applications/${APPLICATION.id}/`).flush({ ...APPLICATION, python_path: '/app/venv/bin/python' });

    await expect(saving).resolves.toMatchObject({ python_path: '/app/venv/bin/python' });
    expect(store.application()?.python_path).toBe('/app/venv/bin/python');
  });

  it('reads the passphrase from the application', async () => {
    await created();

    const capturing = store.capturePassphrase();
    http.expectOne(`/api/applications/${APPLICATION.id}/passphrase/capture/`).flush({ captured: true });

    await expect(capturing).resolves.toBe(true);
    expect(store.captured()).toBe(true);
  });

  it('takes a test backup and follows the job to its end', async () => {
    await created();

    store.takeBackup();
    expect(store.backingUp()).toBe(true);
    const take = http.expectOne('/api/backups/take/');
    expect(take.request.body).toEqual({ application: APPLICATION.id });
    take.flush({ activity: 7 }, { status: 202, statusText: 'Accepted' });

    expect(watch).toHaveBeenCalledWith(7);
    expect(store.backupJob()?.status).toBe('succeeded');
    expect(store.backingUp()).toBe(false);
  });
});
