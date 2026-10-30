import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ApplicationRef, type DebugElement } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { By } from '@angular/platform-browser';
import { provideRouter, type Routes } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { of } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Identity } from '@core/auth/data/auth.types';
import { MASTER, OPERATOR } from '@core/auth/testing/identity.fixtures';
import { errorInterceptor } from '@core/http/error.interceptor';
import { JobWatcher } from '@core/jobs/job-watcher';
import type { Job } from '@core/jobs/job.types';
import { ConfirmedRun } from '@shared/confirmed-run/confirmed-run';
import {
  APPLICATIONS,
  BLOCKED,
  BLOG,
  MOVED,
  MOVE_ID,
  MOVE_STOPPED,
  MOVING,
  PLANNED,
  PLAN_ID,
  RESUMED_ID,
  SERVERS,
  SHOP,
  SOURCE,
  SOURCE_SERVER,
  TARGET,
  pageOf,
} from '../../testing/relocation.fixtures';
import { ServerMovePage } from './server-move';

const ROUTES: Routes = [
  { path: 'servers/:serverId/move', loadChildren: () => import('../../relocation.routes').then((m) => m.routes) },
];

describe('ServerMovePage', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;
  let page: ServerMovePage;
  let watched: Map<number, Job>;

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();
  const render = (): void => harness.detectChanges();
  const root = (): HTMLElement => {
    render();
    return harness.routeNativeElement as HTMLElement;
  };
  const text = (): string => root().textContent?.replace(/\s+/g, ' ') ?? '';
  const buttons = (label: string): HTMLButtonElement[] =>
    Array.from(root().querySelectorAll('button')).filter((button) => button.textContent?.trim() === label);
  const current = (label: string): HTMLButtonElement | undefined =>
    Array.from(root().querySelectorAll('.move__step')[page.step()]?.querySelectorAll('button') ?? []).find(
      (button) => button.textContent?.trim() === label,
    );
  const click = async (label: string): Promise<void> => {
    current(label)?.click();
    await settle();
    render();
  };
  const confirmedRun = (): ConfirmedRun => {
    const found: DebugElement | null | undefined = harness.routeDebugElement?.query(By.directive(ConfirmedRun));
    if (!found) {
      throw new Error('The confirmed run is not on screen.');
    }
    return found.componentInstance as ConfirmedRun;
  };
  const started = (id: number): void => {
    http.expectOne(`/api/servers/${SOURCE}/move/`).flush({ activity: id }, { status: 202, statusText: 'Accepted' });
    render();
  };

  const show = async (query = `?target=${TARGET}`, identity: Identity = MASTER): Promise<void> => {
    harness = await RouterTestingHarness.create();
    const navigating = harness.navigateByUrl(`/servers/${SOURCE}/move${query}`, ServerMovePage);
    (await vi.waitFor(() => http.expectOne('/api/auth/me/'))).flush(identity);
    page = await navigating;
    TestBed.tick();
    http.expectOne(`/api/servers/${SOURCE}/`).flush(SOURCE_SERVER);
    http.expectOne((request) => request.url === '/api/servers/').flush(pageOf(SERVERS));
    http.expectOne((request) => request.url === '/api/applications/').flush(pageOf(APPLICATIONS));
    await settle();
    render();
  };

  const planned = async (job: Job = PLANNED): Promise<void> => {
    watched.set(PLAN_ID, job);
    await show();
    await click('Next');
    await click('Plan the move');
    started(PLAN_ID);
    await settle();
  };

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    watched = new Map();
    TestBed.configureTestingModule({
      providers: [
        { provide: JobWatcher, useValue: { watch: (id: number) => of(watched.get(id)) } },
        { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter(ROUTES),
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it('names the server that moves and offers every other server, the one just added already chosen', async () => {
    await show();

    expect(text()).toContain('From Old web deploy@203.0.113.10:22');
    expect(text()).toContain('New web');
    expect(text()).toContain('Spare');
    expect(page.target()).toBe(TARGET);
    expect(page.targetName()).toBe('New web');
  });

  it('asks for the new server before going on, and offers to add one', async () => {
    await show('');

    await click('Next');

    expect(text()).toContain('Choose the new server.');
    expect(page.step()).toBe(0);
    const add = Array.from(root().querySelectorAll('a')).find((link) => link.textContent?.includes('Add a new server'));
    expect(add?.getAttribute('href')).toBe(`/servers/new?returnTo=%2Fservers%2F${SOURCE}%2Fmove`);
  });

  it('moves every application by default, under its own name and folder, and asks for one at least', async () => {
    await show();
    await click('Next');

    expect(page.choices().map((choice) => [choice.application, choice.name, choice.folder])).toEqual([
      [SHOP, 'Shop', '/srv/shop'],
      [BLOG, 'Blog', '/home/deploy/blog'],
    ]);

    page.update(0, { selected: false });
    page.update(1, { selected: false });
    await click('Plan the move');

    expect(text()).toContain('Choose at least one application.');
    http.expectNone(`/api/servers/${SOURCE}/move/`);
  });

  it('refuses an empty name and a folder that is not absolute', async () => {
    await show();
    await click('Next');

    page.update(0, { name: ' ', folder: 'srv/shop' });
    await click('Plan the move');

    expect(text()).toContain('Enter a name.');
    expect(page.folderError(page.drafts()[0])).toBe('absolute_path_required');
    http.expectNone(`/api/servers/${SOURCE}/move/`);
  });

  it('plans the move as a rehearsal and shows what it carries', async () => {
    await planned();

    expect(page.step()).toBe(2);
    expect(text()).toContain('docker-ce docker-compose-plugin python3-venv');
    expect(text()).toContain('postgres:16 already there');
    expect(current('Next')?.disabled).toBe(false);
  });

  it('says a blocker stops the move and keeps it from going on', async () => {
    await planned(BLOCKED);

    expect(text()).toContain('Something stops the move. Fix what is listed, then plan again.');
    expect(text()).toContain('/srv/shop already holds something on the new server.');
    expect(current('Next')?.disabled).toBe(true);
  });

  it('moves for real with the password, the typed name and the sudo password, then follows it', async () => {
    await planned();
    watched.set(MOVE_ID, MOVING);
    await click('Next');

    expect(text()).toContain('sudo password of ops on New web');
    expect(text()).not.toContain('sudo password of deploy on Old web');
    const run = confirmedRun();
    run.setPassword('hunter2');
    run.setTypedName('New web');
    page.sudoPassword.set('sudo-secret');
    run.runForReal();
    const post = http.expectOne(`/api/servers/${SOURCE}/move/`);
    expect(post.request.body).toEqual({
      target_server: TARGET,
      applications: [
        { application: SHOP, name: 'Shop', folder: '/srv/shop', skip_volumes: [], copy_plans: true },
        { application: BLOG, name: 'Blog', folder: '/home/deploy/blog', skip_volumes: [], copy_plans: true },
      ],
      rehearsal: false,
      password: 'hunter2',
      confirm_name: 'New web',
      sudo_password: 'sudo-secret',
      source_sudo_password: '',
    });
    post.flush({ activity: MOVE_ID }, { status: 202, statusText: 'Accepted' });
    await settle();

    expect(page.sudoPassword()).toBe('');
    expect(page.step()).toBe(4);
    const progress = text();
    expect(progress).toContain('Prepare the new server');
    expect(progress).toContain('Shop to Shop');
    expect(progress).toContain('Carry an image: shop-web:latest');
    expect(progress).toContain('Moved 157.3 MB of the current item');
  });

  it('offers to resume a move that stopped, and resumes it by its job', async () => {
    await planned();
    watched.set(MOVE_ID, MOVE_STOPPED).set(RESUMED_ID, MOVED);
    await click('Next');
    const run = confirmedRun();
    run.setPassword('hunter2');
    run.setTypedName('New web');
    run.runForReal();
    started(MOVE_ID);
    await settle();

    expect(text()).toContain('What arrived differs from what was sent.');
    expect(text()).toContain('/home/ops/.dbs-staging/relocation-32');
    await click('Resume the move');

    expect(page.step()).toBe(3);
    expect(text()).toContain(`This resumes move ${MOVE_ID} from where it stopped.`);
    const again = confirmedRun();
    again.setPassword('hunter2');
    again.setTypedName('New web');
    again.runForReal();
    const resumed = http.expectOne(`/api/servers/${SOURCE}/move/`);
    expect(resumed.request.body).toMatchObject({ rehearsal: false, resume_of: MOVE_ID });
    resumed.flush({ activity: RESUMED_ID }, { status: 202, statusText: 'Accepted' });
    await settle();

    expect(text()).toContain('Old web still runs, untouched');
    const opened = Array.from(root().querySelectorAll('a')).find((link) => link.textContent?.trim() === 'Shop');
    expect(opened?.getAttribute('href')).toBe('/applications/d00d0000-3333-4c7d-9e8f-000000000001');
  });

  it('lets an operator plan the move but never run it', async () => {
    watched.set(PLAN_ID, PLANNED);
    await show(`?target=${TARGET}`, OPERATOR);
    await click('Next');
    await click('Plan the move');
    started(PLAN_ID);
    await settle();
    await click('Next');

    expect(buttons('Move for real')).toHaveLength(0);
    expect(root().querySelector('input[name="password"]')).toBeNull();
    expect(root().querySelector('input[name="sudo_password"]')).toBeNull();
    expect(buttons('Plan again').length).toBeGreaterThan(0);
  });
});
