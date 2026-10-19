import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, type TestRequest } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { TestBed } from '@angular/core/testing';
import { MatButtonHarness } from '@angular/material/button/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatMenuHarness } from '@angular/material/menu/testing';
import { provideRouter, withComponentInputBinding, type Routes } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { NEVER } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Identity } from '@core/auth/data/auth.types';
import { MASTER, OPERATOR } from '@core/auth/testing/identity.fixtures';
import { errorInterceptor } from '@core/http/error.interceptor';
import { JobWatcher } from '@core/jobs/job-watcher';
import { Confirmation } from '@shared/confirm/confirmation';
import { Dialogs } from '@shared/dialogs/dialogs';
import type { DialogHandle } from '@shared/dialogs/dialogs.types';
import { Toaster } from '@shared/toaster/toaster';
import { PlanForm } from '../../components/plan-form/plan-form';
import { RescheduleForm } from '../../components/reschedule-form/reschedule-form';
import type { BackupPlan } from '../../data/plans.types';
import { LOCAL_TIME_ZONE } from '../../data/zoned-time';
import {
  APPLICATION_ID,
  ARCHIVE_PLAN,
  COLLECT_PLAN,
  JOB_ID,
  MANUAL_PLAN,
  PAUSED_PLAN,
  PLAN,
  RIYADH_PLAN,
  pageOf,
} from '../../testing/backups.fixtures';
import { PlansPage } from './plans';

const ROUTES: Routes = [
  {
    path: 'applications/:applicationId',
    children: [{ path: 'schedule', loadChildren: () => import('../../plans.routes').then((m) => m.routes) }],
  },
];

describe('PlansPage', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const plansRequest = (): TestRequest =>
    http.expectOne((request) => request.url === '/api/backups/plans/' && request.method === 'GET');

  const showWith = async (plans: readonly BackupPlan[], identity: Identity = MASTER): Promise<PlansPage> => {
    harness = await RouterTestingHarness.create();
    const navigating = harness.navigateByUrl(`/applications/${APPLICATION_ID}/schedule`, PlansPage);
    (await vi.waitFor(() => http.expectOne('/api/auth/me/'))).flush(identity);
    const page = await navigating;
    TestBed.tick();
    plansRequest().flush(pageOf(plans));
    for (const request of http.match((each) => each.url === '/api/activity/')) {
      request.flush(pageOf([]));
    }
    await settle();
    harness.detectChanges();
    return page;
  };

  const element = (): HTMLElement => harness.routeNativeElement as HTMLElement;

  const rows = (): HTMLTableRowElement[] => Array.from(element().querySelectorAll<HTMLTableRowElement>('tr[mat-row]'));

  const cells = (row: HTMLTableRowElement): string[] =>
    Array.from(row.querySelectorAll('td'), (cell) => (cell.textContent ?? '').replace(/\s+/g, ' ').trim());

  const spyOnDialogs = () => {
    const handle: DialogHandle<unknown> = { closed: NEVER, whenClosed: () => Promise.resolve(undefined) };
    return vi.spyOn(harness.routeDebugElement!.injector.get(Dialogs), 'open').mockReturnValue(handle);
  };

  const menuOf = (plan: BackupPlan): Promise<MatMenuHarness> =>
    TestbedHarnessEnvironment.documentRootLoader(harness.fixture).getHarness(
      MatMenuHarness.with({ selector: `[aria-label="More actions for ${plan.name}"]` }),
    );

  const itemsOf = async (plan: BackupPlan): Promise<string[]> => {
    const menu = await menuOf(plan);
    await menu.open();
    const items = await Promise.all((await menu.getItems()).map((item) => item.getText()));
    await menu.close();
    return items;
  };

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [
        { provide: JobWatcher, useValue: { watch: () => NEVER } },
        { provide: LOCAL_TIME_ZONE, useValue: 'UTC' },
        { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter(ROUTES, withComponentInputBinding()),
      ],
    });
    http = TestBed.inject(HttpTestingController);
    vi.spyOn(TestBed.inject(Toaster), 'add').mockReturnValue(undefined);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("lists the route's application's plans under a second-level title", async () => {
    const page = await showWith([PLAN]);

    expect(page.applicationId()).toBe(APPLICATION_ID);
    expect(element().querySelector('h1')).toBeNull();
    expect(element().querySelector('h2')?.textContent?.trim()).toBe('Plans');
    expect(Array.from(element().querySelectorAll('th'), (header) => header.textContent?.trim())).toEqual([
      'Plan',
      'How often',
      'Kept',
      'Next run',
      'Last run',
      'Actions',
    ]);
  });

  it('says what each plan does, whether it is on or paused, how it last ran and when it runs next', async () => {
    await showWith([PLAN, PAUSED_PLAN, MANUAL_PLAN]);

    const states = rows().map((row) => row.querySelector('td:nth-child(2) app-status-tag')?.textContent?.trim());
    expect(states).toEqual(['On', 'Paused', undefined]);
    const [daily, paused, manual] = rows().map(cells);
    expect(daily[0]).toContain('django-dbs');
    expect(daily[1]).toContain('Daily');
    expect(daily[2]).toContain('Here: 3');
    expect(daily[2]).toContain('On the server: 1');
    expect(daily[3]).toContain('Oct 1, 2026, 12:00 AM');
    expect(daily[3]).toContain('UTC');
    expect(daily[3]).not.toContain('Your time');
    expect(daily[4]).toContain('Succeeded');

    expect(paused[1]).toContain('Every hour');
    expect(paused[3]).toBe('—');
    expect(paused[4]).toBe('Not run yet');

    expect(manual[1]).toBe('Manual');
    expect(manual[3]).toBe('—');
    expect(manual[4]).toContain('Failed');
    expect(manual[4]).toContain('The server did not answer over SSH.');
  });

  it("shows the next run in the plan's zone, and the reader's own time when it differs", async () => {
    await showWith([RIYADH_PLAN]);

    const next = rows()[0].querySelector('app-next-run');
    expect(next?.querySelector('time')?.getAttribute('datetime')).toBe(RIYADH_PLAN.next_run_at);
    const shown = (next?.textContent ?? '').replace(/\s+/g, ' ');
    expect(shown).toContain('Oct 2, 2026, 2:00 AM');
    expect(shown).toContain('Asia/Riyadh');
    expect(shown).toContain('Your time: Oct 1, 2026, 11:00 PM');
  });

  it('lists the folders a folder plan archives, and where a collection reads from, left to right', async () => {
    await showWith([ARCHIVE_PLAN, COLLECT_PLAN]);

    const [media, dumps] = rows();
    expect(media.textContent).toContain('Folders: 2');
    expect(Array.from(media.querySelectorAll('li bdi'), (path) => [path.textContent, path.getAttribute('dir')])).toEqual([
      ['/srv/app/media', 'ltr'],
      ['/srv/app/uploads', 'ltr'],
    ]);
    expect(dumps.textContent).toContain('Existing files');
    expect(dumps.textContent).not.toContain('On the server');
    expect(dumps.querySelector('bdi.plans__code')?.textContent).toBe('/var/backups/postgres/*.sql.gz');
  });

  it('offers a first django-dbs plan when the application has none, and opens the form for each kind', async () => {
    await showWith([]);
    const open = spyOnDialogs();

    const empty = element().querySelector('app-empty-state');
    expect(empty?.textContent).toContain('No plans yet');
    expect(element().querySelector('.plans__header button')).toBeNull();
    const [first, folders, collect] = Array.from(empty?.querySelectorAll('button') ?? []);

    first.click();
    expect(open).toHaveBeenLastCalledWith(PlanForm, expect.objectContaining({ data: { plan: null, name: 'django-dbs' } }));
    folders.click();
    expect(open).toHaveBeenLastCalledWith(PlanForm, expect.objectContaining({ data: { plan: null, kind: 'archive' } }));
    collect.click();
    expect(open).toHaveBeenLastCalledWith(PlanForm, expect.objectContaining({ data: { plan: null, kind: 'collect' } }));

    const offers = await TestbedHarnessEnvironment.loader(harness.fixture).getAllHarnesses(
      MatButtonHarness.with({ ancestor: 'app-empty-state' }),
    );
    expect(await Promise.all(offers.map((offer) => offer.getAppearance()))).toEqual(['filled', 'outlined', 'outlined']);
  });

  it('adds a plan from its one filled button above the list', async () => {
    await showWith([PLAN]);
    const open = spyOnDialogs();

    const filled = await TestbedHarnessEnvironment.loader(harness.fixture).getAllHarnesses(
      MatButtonHarness.with({ appearance: 'filled' }),
    );
    expect(await Promise.all(filled.map((each) => each.getText()))).toEqual(['Add plan']);
    await filled[0].click();

    expect(open).toHaveBeenCalledWith(PlanForm, expect.objectContaining({ titleKey: 'backups.plans.form.addTitle' }));
  });

  it('runs a plan from its row and says a backup is running', async () => {
    const page = await showWith([PLAN]);

    element().querySelector<HTMLButtonElement>(`button[aria-label="Run ${PLAN.name} now"]`)?.click();
    http.expectOne(`/api/backups/plans/${PLAN.id}/run/`).flush({ activity: JOB_ID });
    harness.detectChanges();

    expect(page.isRunning(PLAN)).toBe(true);
    expect(element().querySelector('app-notice')?.textContent).toContain('A backup is running.');
    expect(element().querySelector<HTMLButtonElement>(`button[aria-label="Run ${PLAN.name} now"]`)?.textContent).toContain(
      'Running…',
    );
  });

  it('offers pausing and moving a plan that is on, resuming a paused one, and neither for a manual one', async () => {
    await showWith([PLAN, PAUSED_PLAN, MANUAL_PLAN]);

    expect(await itemsOf(PLAN)).toEqual(['Pause', 'Reschedule', 'Edit', 'Delete']);
    expect(await itemsOf(PAUSED_PLAN)).toEqual(['Resume', 'Edit', 'Delete']);
    expect(await itemsOf(MANUAL_PLAN)).toEqual(['Edit', 'Delete']);
  });

  it('pauses and resumes a plan from its menu', async () => {
    await showWith([PLAN, PAUSED_PLAN]);

    await (await menuOf(PLAN)).clickItem({ text: 'Pause' });
    http.expectOne(`/api/backups/plans/${PLAN.id}/pause/`).flush({ ...PLAN, enabled: false, next_run_at: null });
    await settle();
    TestBed.tick();
    plansRequest().flush(pageOf([{ ...PLAN, enabled: false, next_run_at: null }, PAUSED_PLAN]));
    await settle();

    await (await menuOf(PAUSED_PLAN)).clickItem({ text: 'Resume' });
    http.expectOne(`/api/backups/plans/${PAUSED_PLAN.id}/resume/`).flush({ ...PAUSED_PLAN, enabled: true });
    await settle();
    TestBed.tick();
    plansRequest().flush(pageOf([PLAN, { ...PAUSED_PLAN, enabled: true }]));
    await settle();
  });

  it('opens the reschedule dialog and the plan form from the menu', async () => {
    await showWith([PLAN]);
    const open = spyOnDialogs();

    await (await menuOf(PLAN)).clickItem({ text: 'Reschedule' });
    expect(open).toHaveBeenLastCalledWith(
      RescheduleForm,
      expect.objectContaining({ titleKey: 'backups.plans.reschedule.title', data: { plan: PLAN } }),
    );

    await (await menuOf(PLAN)).clickItem({ text: 'Edit' });
    expect(open).toHaveBeenLastCalledWith(
      PlanForm,
      expect.objectContaining({ titleKey: 'backups.plans.form.editTitle', data: { plan: PLAN } }),
    );
  });

  it('asks before deleting a plan, saying its backups stay', async () => {
    await showWith([PLAN]);
    const ask = vi.spyOn(TestBed.inject(Confirmation), 'ask').mockResolvedValueOnce(false).mockResolvedValueOnce(true);

    await (await menuOf(PLAN)).clickItem({ text: 'Delete' });
    await vi.waitFor(() => expect(ask).toHaveBeenCalledOnce());
    expect(ask).toHaveBeenCalledWith(
      expect.objectContaining({
        title: `Delete ⁨${PLAN.name}⁩?`,
        message: 'The plan stops running. Its backups stay listed until someone deletes them.',
        acceptSeverity: 'danger',
      }),
    );
    http.expectNone(`/api/backups/plans/${PLAN.id}/`);

    await (await menuOf(PLAN)).clickItem({ text: 'Delete' });
    const request = await vi.waitFor(() => http.expectOne(`/api/backups/plans/${PLAN.id}/`));
    expect(request.request.method).toBe('DELETE');
    request.flush(null, { status: 204, statusText: 'No Content' });
    await settle();
    TestBed.tick();
    plansRequest().flush(pageOf([]));
    await settle();
  });

  it('lets an operator run a plan, and nothing more', async () => {
    await showWith([PLAN], OPERATOR);

    expect(element().querySelector(`button[aria-label="Run ${PLAN.name} now"]`)).not.toBeNull();
    expect(element().querySelector(`button[aria-label="More actions for ${PLAN.name}"]`)).toBeNull();
    expect(element().querySelector('.plans__header button')).toBeNull();
  });
});
