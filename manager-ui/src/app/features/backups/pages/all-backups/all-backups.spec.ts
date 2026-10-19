import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, type TestRequest } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { TestBed } from '@angular/core/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatSelectHarness } from '@angular/material/select/testing';
import { provideRouter, withComponentInputBinding, type Routes } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { NEVER } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { MASTER } from '@core/auth/testing/identity.fixtures';
import { errorInterceptor } from '@core/http/error.interceptor';
import { JobWatcher } from '@core/jobs/job-watcher';
import { Dialogs } from '@shared/dialogs/dialogs';
import type { DialogHandle } from '@shared/dialogs/dialogs.types';
import { Toaster } from '@shared/toaster/toaster';
import { RestoreForm } from '../../components/restore-form/restore-form';
import type { BackupFile, Dashboard } from '../../data/backups.types';
import {
  APPLICATIONS,
  APPLICATION_ID,
  BLOG,
  BLOG_FILE,
  DASHBOARD,
  FILE,
  OTHER_APPLICATION_ID,
  OTHER_SERVER_ID,
  SERVER_ID,
  pageOf,
} from '../../testing/backups.fixtures';
import { AllBackupsPage } from './all-backups';

const ROUTES: Routes = [{ path: 'backups', loadChildren: () => import('../../all-backups.routes').then((m) => m.routes) }];

describe('AllBackupsPage', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const listRequest = (): TestRequest => http.expectOne((request) => request.url === '/api/backups/');

  const show = async (
    files: readonly BackupFile[] = [FILE, BLOG_FILE],
    dashboard: Dashboard = DASHBOARD,
  ): Promise<AllBackupsPage> => {
    harness = await RouterTestingHarness.create();
    const navigating = harness.navigateByUrl('/backups', AllBackupsPage);
    (await vi.waitFor(() => http.expectOne('/api/auth/me/'))).flush(MASTER);
    const page = await navigating;
    TestBed.tick();
    listRequest().flush(pageOf(files));
    http.expectOne((request) => request.url === '/api/applications/').flush(pageOf(APPLICATIONS));
    http.expectOne('/api/dashboard/').flush(dashboard);
    for (const request of http.match((each) => each.url === '/api/activity/')) {
      request.flush(pageOf([]));
    }
    await settle();
    harness.detectChanges();
    return page;
  };

  const element = (): HTMLElement => harness.routeNativeElement as HTMLElement;

  const tables = (): HTMLTableElement[] => Array.from(element().querySelectorAll('table'));

  const rowsOf = (table: HTMLTableElement): string[][] =>
    Array.from(table.querySelectorAll('tr[mat-row]'), (row) =>
      Array.from(row.querySelectorAll('td'), (cell) => (cell.textContent ?? '').replace(/\s+/g, ' ').trim()),
    );

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [
        { provide: JobWatcher, useValue: { watch: () => NEVER } },
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

  it('names the page, then the storage and every backup under their own titles', async () => {
    await show();

    expect(element().querySelector('h1')?.textContent?.trim()).toBe('Backups');
    expect(Array.from(element().querySelectorAll('h2'), (heading) => heading.textContent?.trim())).toEqual([
      'Storage',
      'Every backup',
    ]);
  });

  it("adds up the manager's storage, the largest application first, linking each one and its server", async () => {
    await show();

    expect(element().querySelector('.all-backups__total')?.textContent).toContain('5.4 MB');
    const [storage] = tables();
    expect(storage.getAttribute('aria-label')).toBe('Storage by application');
    expect(rowsOf(storage)).toEqual([
      ['blog', 'staging-web', '4 MB'],
      ['shop', 'production-web', '1.4 MB'],
    ]);
    const links = Array.from(storage.querySelectorAll('a'), (link) => link.getAttribute('href'));
    expect(links).toEqual([
      `/applications/${OTHER_APPLICATION_ID}`,
      `/servers/${OTHER_SERVER_ID}`,
      `/applications/${APPLICATION_ID}`,
      `/servers/${SERVER_ID}`,
    ]);
  });

  it('says how much of the disk under the backups is still free', async () => {
    await show();

    expect(element().querySelector('.all-backups__free')?.textContent?.trim()).toBe('62 GB of 100 GB');
    expect(element().querySelector('app-notice')).toBeNull();
  });

  it('warns when the disk under the backups is nearly full', async () => {
    await show([FILE], { ...DASHBOARD, disk: { total_bytes: 100_000_000_000, free_bytes: 900_000_000, low: true } });

    expect(element().querySelector('.all-backups__free')?.textContent?.trim()).toBe('900 MB of 100 GB');
    expect(element().querySelector('app-notice[severity="warning"]')?.textContent).toContain('nearly full');
  });

  it('pages the storage of many applications ten at a time', async () => {
    const many: Dashboard = {
      storage_bytes: 12_000,
      disk: null,
      servers: [
        {
          id: SERVER_ID,
          name: 'production-web',
          applications: Array.from({ length: 12 }, (_, index) => ({
            id: `app-${index}`,
            name: `app-${String(index).padStart(2, '0')}`,
            storage_bytes: 1_000,
          })),
        },
      ],
    };
    await show([FILE], many);

    const [storage] = tables();
    expect(rowsOf(storage).length).toBe(10);
    expect(element().querySelector('nav[aria-label="Storage pages"] mat-paginator')).not.toBeNull();
  });

  it('lists every backup with its application and server, each a link', async () => {
    await show();

    const files = tables()[1];
    expect(files.getAttribute('aria-label')).toBe('Every backup');
    expect(Array.from(files.querySelectorAll('th'), (header) => header.textContent?.trim())).toEqual([
      'Name',
      'Application',
      'Server',
      'Taken',
      'Plan',
      'Size',
      'Check',
      'Actions',
    ]);
    const [shop, blog] = Array.from(files.querySelectorAll('tr[mat-row]'));
    const owners = shop.querySelectorAll('a[href^="/applications/"], a[href^="/servers/"]');
    expect(Array.from(owners, (link) => link.getAttribute('href'))).toEqual([
      `/applications/${APPLICATION_ID}`,
      `/servers/${SERVER_ID}`,
    ]);
    expect(blog.textContent).toContain('blog');
    expect(blog.textContent).toContain('staging-web');
    expect(blog.querySelector(`button[aria-label="Verify ${BLOG_FILE.name}"]`)).not.toBeNull();
  });

  it('restores from here through the same form', async () => {
    await show();
    const handle: DialogHandle<unknown> = { closed: NEVER, whenClosed: () => Promise.resolve(undefined) };
    const open = vi.spyOn(harness.routeDebugElement!.injector.get(Dialogs), 'open').mockReturnValue(handle);

    element().querySelector<HTMLButtonElement>(`button[aria-label="Restore ${BLOG_FILE.name}"]`)?.click();

    expect(open).toHaveBeenCalledWith(RestoreForm, expect.objectContaining({ data: { file: BLOG_FILE } }));
  });

  it('filters by one application, and offers every one back when it has none', async () => {
    await show();

    const filter = await TestbedHarnessEnvironment.loader(harness.fixture).getHarness(MatSelectHarness);
    await filter.open();
    const options = await filter.getOptions();
    expect(await Promise.all(options.map((option) => option.getText()))).toEqual([
      'Every application',
      '⁨shop⁩ on ⁨production-web⁩',
      `⁨${BLOG.name}⁩ on ⁨${BLOG.server.name}⁩`,
    ]);
    // A harness click waits for the list it starts loading, so the option is clicked as a person would.
    document.querySelectorAll<HTMLElement>('mat-option')[2].click();
    TestBed.tick();

    const filtered = listRequest();
    expect(filtered.request.params.get('application')).toBe(OTHER_APPLICATION_ID);
    filtered.flush(pageOf([]));
    await settle();
    harness.detectChanges();

    const empty = element().querySelector('app-empty-state');
    expect(empty?.textContent).toContain('No backups for this application');
    empty?.querySelector('button')?.click();
    TestBed.tick();
    const every = listRequest();
    expect(every.request.params.has('application')).toBe(false);
    every.flush(pageOf([FILE, BLOG_FILE]));
    await settle();
  });

  it('says there are no backups yet anywhere', async () => {
    await show([], { storage_bytes: 0, servers: [], disk: null });

    expect(element().querySelector('.all-backups__total')?.textContent).toContain('0 bytes');
    expect(tables()).toEqual([]);
    const empty = element().querySelector('app-empty-state');
    expect(empty?.textContent).toContain('No backups yet');
    expect(empty?.textContent).toContain('Backups appear here once an application has one.');
  });

  it('says why the storage could not be read, and reads it again', async () => {
    harness = await RouterTestingHarness.create();
    const navigating = harness.navigateByUrl('/backups', AllBackupsPage);
    (await vi.waitFor(() => http.expectOne('/api/auth/me/'))).flush(MASTER);
    await navigating;
    TestBed.tick();
    listRequest().flush(pageOf([FILE]));
    http.expectOne((request) => request.url === '/api/applications/').flush(pageOf(APPLICATIONS));
    http
      .expectOne('/api/dashboard/')
      .flush({ error: { code: 'unknown', message: 'Server prose' } }, { status: 500, statusText: 'Error' });
    for (const request of http.match((each) => each.url === '/api/activity/')) {
      request.flush(pageOf([]));
    }
    await settle();
    harness.detectChanges();

    const card = element().querySelector('mat-card');
    expect(card?.querySelector('app-notice')?.textContent).toContain('Something went wrong.');
    card?.querySelector('button')?.click();
    TestBed.tick();
    http.expectOne('/api/dashboard/').flush(DASHBOARD);
    await settle();
    harness.detectChanges();
    expect(element().querySelector('.all-backups__total')?.textContent).toContain('5.4 MB');
  });
});
