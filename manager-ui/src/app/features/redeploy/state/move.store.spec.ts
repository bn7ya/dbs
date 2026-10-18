import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { JobWatcher } from '@core/jobs/job-watcher';
import type { Job } from '@core/jobs/job.types';
import type { MoveRequest } from '../data/redeploy.types';
import {
  APPLICATIONS,
  BACKUPS,
  ENV_VERSIONS,
  MOVE_ID,
  MOVE_STOPPED,
  REVERTED,
  REVERT_ID,
  SOURCE,
  TARGET,
  pageOf,
} from '../testing/redeploy.fixtures';
import { MoveStore } from './move.store';

const MOVE: MoveRequest = {
  source_application: SOURCE,
  target_application: TARGET,
  backup: 'b-new',
  env_version: null,
  flush: false,
  rehearsal: false,
  password: 'hunter2',
  confirm_name: 'Shop next',
};

describe('MoveStore', () => {
  let store: MoveStore;
  let http: HttpTestingController;
  let watched: Map<number, Job>;

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const open = async (): Promise<void> => {
    store.open(SOURCE);
    TestBed.tick();
    http.expectOne((request) => request.url === '/api/applications/').flush(pageOf(APPLICATIONS));
    http.expectOne((request) => request.url === '/api/backups/').flush(pageOf(BACKUPS));
    http.expectOne((request) => request.url === '/api/envfiles/').flush(pageOf(ENV_VERSIONS));
    await settle();
  };

  beforeEach(() => {
    watched = new Map();
    TestBed.configureTestingModule({
      providers: [
        MoveStore,
        { provide: JobWatcher, useValue: { watch: (id: number) => of(watched.get(id)) } },
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    store = TestBed.inject(MoveStore);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
  });

  it('reads nothing until the page opens an application', () => {
    TestBed.tick();

    http.expectNone(() => true);
    expect(store.targets()).toEqual([]);
  });

  it('offers every other application, and only its django-dbs backups', async () => {
    await open();

    expect(store.targets().map((application) => application.id)).toEqual([TARGET]);
    expect(store.backups().map((backup) => backup.id)).toEqual(['b-new', 'b-old']);
    expect(store.envVersions()).toEqual(ENV_VERSIONS);
    expect(store.loading()).toBe(false);
  });

  it('says why a list could not be read, and reads them again', async () => {
    store.open(SOURCE);
    TestBed.tick();
    http.expectOne((request) => request.url === '/api/applications/').flush(pageOf(APPLICATIONS));
    http
      .expectOne((request) => request.url === '/api/backups/')
      .flush({ error: { code: 'network', message: 'Server prose' } }, { status: 503, statusText: 'Down' });
    http.expectOne((request) => request.url === '/api/envfiles/').flush(pageOf(ENV_VERSIONS));
    await settle();
    expect(store.loadError()?.code).toBe('network');

    store.reload();
    TestBed.tick();
    http.expectOne((request) => request.url === '/api/applications/').flush(pageOf(APPLICATIONS));
    http.expectOne((request) => request.url === '/api/backups/').flush(pageOf(BACKUPS));
    http.expectOne((request) => request.url === '/api/envfiles/').flush(pageOf(ENV_VERSIONS));
    await settle();
    expect(store.loadError()).toBeNull();
  });

  it('moves, knows where the move went, and reverts it there', async () => {
    watched.set(MOVE_ID, MOVE_STOPPED).set(REVERT_ID, REVERTED);
    await open();

    store.move(MOVE);
    const post = http.expectOne('/api/redeploy/');
    expect(post.request.body).toEqual(MOVE);
    post.flush({ activity: MOVE_ID }, { status: 202, statusText: 'Accepted' });

    expect(store.moving.job()).toEqual(MOVE_STOPPED);
    expect(store.outcome().revertable).toBe(true);
    expect(store.movedTo()?.name).toBe('Shop next');

    const undo = { rehearsal: true, password: '', confirm_name: '' };
    store.revert(undo);
    const revert = http.expectOne(`/api/redeploy/${MOVE_ID}/revert/`);
    expect(revert.request.body).toEqual(undo);
    revert.flush({ activity: REVERT_ID }, { status: 202, statusText: 'Accepted' });
    expect(store.reverting.job()).toEqual(REVERTED);
    expect(store.reverting.rehearsal()).toBe(true);

    store.move({ ...MOVE, rehearsal: true });
    expect(store.reverting.job()).toBeNull();
    http.expectOne('/api/redeploy/').flush({ activity: MOVE_ID }, { status: 202, statusText: 'Accepted' });
  });

  it('reverts nothing before a move', async () => {
    await open();

    store.revert({ rehearsal: true, password: '', confirm_name: '' });

    http.expectNone((request) => request.url.includes('/revert/'));
  });
});
