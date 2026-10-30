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
import type { MoveChoice } from '../data/relocation.types';
import {
  APPLICATIONS,
  BLOCKED,
  INVENTORY,
  MOVED,
  MOVE_ID,
  MOVING,
  PLANNED,
  PLAN_ID,
  SERVERS,
  SHOP,
  SOURCE,
  SOURCE_SERVER,
  TARGET,
  pageOf,
} from '../testing/relocation.fixtures';
import { ServerMoveStore } from './server-move.store';

const CHOICES: readonly MoveChoice[] = [
  { application: SHOP, name: 'Shop', folder: '/srv/shop', skip_volumes: [], copy_plans: true },
];

describe('ServerMoveStore', () => {
  let store: ServerMoveStore;
  let http: HttpTestingController;
  let watched: Map<number, Job>;

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const open = async (): Promise<void> => {
    store.open(SOURCE);
    TestBed.tick();
    http.expectOne(`/api/servers/${SOURCE}/`).flush(SOURCE_SERVER);
    http.expectOne((request) => request.url === '/api/servers/').flush(pageOf(SERVERS));
    http.expectOne((request) => request.url === '/api/applications/').flush(pageOf(APPLICATIONS));
    await settle();
  };

  const started = (id: number): void => {
    http.expectOne(`/api/servers/${SOURCE}/move/`).flush({ activity: id }, { status: 202, statusText: 'Accepted' });
  };

  beforeEach(() => {
    watched = new Map();
    TestBed.configureTestingModule({
      providers: [
        ServerMoveStore,
        { provide: JobWatcher, useValue: { watch: (id: number) => of(watched.get(id)) } },
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    store = TestBed.inject(ServerMoveStore);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
  });

  it('reads nothing until the page opens a server', () => {
    TestBed.tick();

    http.expectNone(() => true);
    expect(store.targets()).toEqual([]);
    expect(store.applications()).toEqual([]);
  });

  it('offers every other server as the target, and the applications of this one', async () => {
    await open();

    expect(store.source()).toEqual(SOURCE_SERVER);
    expect(store.targets().map((server) => server.id)).not.toContain(SOURCE);
    expect(store.targets()).toHaveLength(2);
    expect(store.applications()).toEqual(APPLICATIONS);
    expect(store.loading()).toBe(false);
    expect(store.loadError()).toBeNull();
  });

  it('says why a list could not be read', async () => {
    store.open(SOURCE);
    TestBed.tick();
    http.expectOne(`/api/servers/${SOURCE}/`).flush(SOURCE_SERVER);
    http
      .expectOne((request) => request.url === '/api/servers/')
      .flush({ error: { code: 'role_required', message: 'Server prose' } }, { status: 403, statusText: 'Forbidden' });
    http.expectOne((request) => request.url === '/api/applications/').flush(pageOf(APPLICATIONS));
    await settle();

    expect(store.loadError()?.code).toBe('role_required');
  });

  it('rehearses with no secret at all and reads the plan from the job', async () => {
    watched.set(PLAN_ID, PLANNED);
    await open();

    store.rehearse(TARGET, CHOICES);
    const post = http.expectOne(`/api/servers/${SOURCE}/move/`);
    expect(post.request.body).toEqual({
      target_server: TARGET,
      applications: CHOICES,
      rehearsal: true,
      password: '',
      confirm_name: '',
      sudo_password: '',
      source_sudo_password: '',
    });
    post.flush({ activity: PLAN_ID }, { status: 202, statusText: 'Accepted' });

    expect(store.planned()).toBe(true);
    expect(store.planBlocked()).toBe(false);
    expect(store.plan()?.inventory).toEqual(INVENTORY);
    expect(store.plan()?.rehearsal).toBe(true);
  });

  it('knows when a blocker stopped the plan', async () => {
    watched.set(PLAN_ID, BLOCKED);
    await open();

    store.rehearse(TARGET, CHOICES);
    started(PLAN_ID);

    expect(store.planned()).toBe(false);
    expect(store.planBlocked()).toBe(true);
    expect(store.plan()?.blockers.map((blocker) => blocker.code)).toEqual(['target_folder_not_empty', 'sudo_missing']);
  });

  it('moves for real with the passwords, and resumes a stopped move by its job', async () => {
    watched.set(MOVE_ID, MOVING);
    await open();
    const run = { rehearsal: false, password: 'hunter2', confirm_name: 'New web' };

    store.move(TARGET, CHOICES, run, 'sudo-secret', '', null);
    const post = http.expectOne(`/api/servers/${SOURCE}/move/`);
    expect(post.request.body).toEqual({
      target_server: TARGET,
      applications: CHOICES,
      rehearsal: false,
      password: 'hunter2',
      confirm_name: 'New web',
      sudo_password: 'sudo-secret',
      source_sudo_password: '',
    });
    post.flush({ activity: MOVE_ID }, { status: 202, statusText: 'Accepted' });
    expect(store.progress()?.current?.key).toBe('shop-web:latest');
    expect(store.moveFinished()).toBe(false);

    watched.set(MOVE_ID + 1, MOVED);
    store.moving.forget();
    store.move(TARGET, CHOICES, run, '', 'source-secret', MOVE_ID);
    const resumed = http.expectOne(`/api/servers/${SOURCE}/move/`);
    expect(resumed.request.body).toMatchObject({ resume_of: MOVE_ID, source_sudo_password: 'source-secret' });
    resumed.flush({ activity: MOVE_ID + 1 }, { status: 202, statusText: 'Accepted' });
    expect(store.moveFinished()).toBe(true);
    expect(store.progress()?.created.map((application) => application.name)).toEqual(['Shop']);
  });

  it('starts nothing before a server is open', () => {
    store.rehearse(TARGET, CHOICES);
    store.move(TARGET, CHOICES, { rehearsal: false, password: 'x', confirm_name: 'y' }, '', '', null);

    http.expectNone(() => true);
  });
});
