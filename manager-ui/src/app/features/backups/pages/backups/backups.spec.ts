import { HttpEventType, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, type TestRequest } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { TestBed } from '@angular/core/testing';
import { MatButtonHarness } from '@angular/material/button/testing';
import { provideRouter, withComponentInputBinding, type Routes } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { NEVER } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Identity } from '@core/auth/data/auth.types';
import { errorInterceptor } from '@core/http/error.interceptor';
import { JobWatcher } from '@core/jobs/job-watcher';
import { Confirmation } from '@shared/confirm/confirmation';
import { Dialogs } from '@shared/dialogs/dialogs';
import type { DialogHandle } from '@shared/dialogs/dialogs.types';
import { Toaster } from '@shared/toaster/toaster';
import { PlanForm } from '../../components/plan-form/plan-form';
import { RestoreForm } from '../../components/restore-form/restore-form';
import type { BackupFile, BackupPlan } from '../../data/backups.types';
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
  pageOf,
} from '../../testing/backups.fixtures';
import { BackupsStore } from '../../state/backups.store';
import { BackupsPage } from './backups';

const IDENTITY: Identity = {
  id: 1,
  username: 'sara',
  email: 'sara@example.com',
  first_name: 'Sara',
  last_name: 'Hassan',
  is_staff: false,
  is_superuser: false,
  groups: [],
  permissions: [],
};

const ROUTES: Routes = [
  {
    path: 'servers/:serverId',
    children: [{ path: 'backups', loadChildren: () => import('../../backups.routes').then((m) => m.routes) }],
  },
];

describe('BackupsPage', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const listRequest = (): TestRequest => http.expectOne((request) => request.url === '/api/backups/');
  const plansRequest = (): TestRequest => http.expectOne((request) => request.url === '/api/backups/plans/');

  const answerPlansAndJobs = (plans: readonly BackupPlan[] = [PLAN]): void => {
    plansRequest().flush(pageOf(plans));
    for (const request of http.match((each) => each.url === '/api/activity/')) {
      request.flush(pageOf([]));
    }
  };

  const show = async (): Promise<BackupsPage> => {
    harness = await RouterTestingHarness.create();
    const navigating = harness.navigateByUrl(`/servers/${SERVER_ID}/backups`, BackupsPage);
    const me = await vi.waitFor(() => http.expectOne('/api/auth/me/'));
    me.flush(IDENTITY);
    const page = await navigating;
    TestBed.tick();
    return page;
  };

  const showWith = async (
    results: readonly BackupFile[],
    count = results.length,
    plans: readonly BackupPlan[] = [PLAN],
  ): Promise<BackupsPage> => {
    const page = await show();
    listRequest().flush(pageOf(results, count));
    answerPlansAndJobs(plans);
    await settle();
    harness.detectChanges();
    return page;
  };

  const text = (): string => element().textContent ?? '';

  const element = (): HTMLElement => harness.routeNativeElement as HTMLElement;

  const spyOnDialogs = () => {
    const handle: DialogHandle<unknown> = { closed: NEVER, whenClosed: () => Promise.resolve(undefined) };
    return vi.spyOn(harness.routeDebugElement!.injector.get(Dialogs), 'open').mockReturnValue(handle);
  };

  const fileRows = (): HTMLTableRowElement[] =>
    Array.from(element().querySelectorAll('table')[1].querySelectorAll<HTMLTableRowElement>('tr[mat-row]'));

  const planRows = (): HTMLTableRowElement[] =>
    Array.from(element().querySelectorAll('table')[0].querySelectorAll<HTMLTableRowElement>('tr[mat-row]'));

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [
        // The page's spec is not about following a job; the store's is.
        { provide: JobWatcher, useValue: { watch: () => NEVER } },
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

  it("lists the route's server under second-level titles, with a link to download each file", async () => {
    const page = await show();

    expect(page.serverId()).toBe(SERVER_ID);
    const request = listRequest();
    expect(request.request.params.get('server')).toBe(SERVER_ID);
    request.flush(pageOf([FILE, VERIFIED]));
    answerPlansAndJobs();
    await settle();
    harness.detectChanges();

    expect(element().querySelector('h1')).toBeNull();
    const titles = Array.from(element().querySelectorAll('h2'), (heading) => heading.textContent?.trim());
    expect(titles).toEqual(['Plans', 'Backups']);
    expect(text()).toContain(FILE.name);
    const download = element().querySelector<HTMLAnchorElement>(`a[href="/api/backups/${FILE.id}/download/"]`);
    expect(download?.getAttribute('download')).toBe(FILE.name);
    expect(download?.getAttribute('aria-label')).toBe(`Download ${FILE.name}`);
  });

  it('leaves the pages out while one page holds every file', async () => {
    await showWith([FILE], 20);
    expect(element().querySelector('mat-paginator')).toBeNull();
  });

  it('pages a list longer than one page', async () => {
    await showWith([FILE], 21);
    expect(element().querySelector('mat-paginator')).not.toBeNull();
  });

  it('says there are no backups yet', async () => {
    await showWith([]);
    expect(element().querySelector('app-empty-state')?.textContent).toContain('No backups yet');
  });

  it('shows which plan made each file, and who took it when someone did', async () => {
    await showWith([FILE, VERIFIED]);

    const rows = fileRows().map((row) => row.textContent);
    expect(rows[0]).toContain('One-off');
    expect(rows[0]).toContain('By ⁨sara⁩');
    expect(rows[1]).toContain(PLAN.name);
    expect(rows[1]).not.toContain('By ');
  });

  it('tags each file with what made it', async () => {
    await showWith([FILE, ARCHIVE_FILE, COLLECTED_FILE, UPLOADED_FILE]);

    const tags = fileRows().map((row) => row.querySelector('td:first-child app-status-tag')?.textContent?.trim());
    expect(tags).toEqual(['django-dbs', 'Folders', 'Collected', 'Uploaded']);
  });

  it("calls a django-dbs file's check django-dbs's, and a sealed file's only what the seal shows", async () => {
    await showWith([
      FILE,
      { ...FILE, id: 'verified-dbs', validation: 'verified' },
      { ...UPLOADED_FILE, validation: 'verified' },
      { ...ARCHIVE_FILE, validation: 'failed' },
      COLLECTED_FILE,
    ]);

    const checks = fileRows().map((row) =>
      Array.from(row.querySelectorAll('td:nth-child(5) app-status-tag'), (tag) => tag.textContent?.trim()),
    );
    expect(checks).toEqual([['Structure checked'], ['Verified'], ['Intact'], ['Damaged'], ['Stored']]);
  });

  describe('uploading a file', () => {
    const picker = (): HTMLInputElement => {
      const input = element().querySelector<HTMLInputElement>('input[type="file"]');
      if (input === null) {
        throw new Error('no file picker on the page');
      }
      return input;
    };

    const choose = (file: File): void => {
      const files = { 0: file, length: 1, item: (index: number) => (index === 0 ? file : null) };
      Object.defineProperty(picker(), 'files', { value: files, configurable: true });
      picker().dispatchEvent(new Event('change'));
    };

    const uploadButton = (): HTMLButtonElement | undefined =>
      Array.from(element().querySelectorAll('button')).find((button) => button.textContent?.trim() === 'Upload a backup');

    it('opens the hidden picker from its button', async () => {
      await showWith([FILE]);
      const opened = vi.spyOn(picker(), 'click').mockImplementation(() => undefined);

      expect(picker().hidden).toBe(true);
      const button = await TestbedHarnessEnvironment.loader(harness.fixture).getHarness(
        MatButtonHarness.with({ text: 'Upload a backup' }),
      );
      expect(await button.getAppearance()).toBe('outlined');
      uploadButton()?.click();

      expect(opened).toHaveBeenCalledOnce();
    });

    it('shows the file on its way, read left to right, with its share sent and a way to cancel it', async () => {
      await showWith([FILE]);
      choose(new File(['abcd'], UPLOADED_FILE.name));
      const request = http.expectOne('/api/backups/upload/');
      request.event({ type: HttpEventType.UploadProgress, loaded: 1, total: 4 });
      harness.detectChanges();

      expect(picker().value).toBe('');
      const progress = element().querySelector('mat-progress-bar');
      expect(progress?.getAttribute('aria-valuenow')).toBe('25');
      expect(element().querySelector('.backups__upload-status')?.textContent).toContain('Uploading…');
      const name = element().querySelector('.backups__upload bdi');
      expect(name?.textContent).toBe(UPLOADED_FILE.name);
      expect(name?.getAttribute('dir')).toBe('ltr');

      const cancel = element().querySelector<HTMLButtonElement>('.backups__upload button');
      expect(cancel?.getAttribute('aria-label')).toBe(`Cancel the upload of ${UPLOADED_FILE.name}`);
      cancel?.focus();
      cancel?.click();
      harness.detectChanges();

      await settle();

      expect(request.cancelled).toBe(true);
      expect(element().querySelector('mat-progress-bar')).toBeNull();
      // Cancel took itself off the page; focus is back on the button that started the upload.
      expect(document.activeElement).toBe(uploadButton());
    });

    it('says the file is being saved once every byte is sent, with nothing left to cancel', async () => {
      await showWith([FILE]);
      choose(new File(['abcd'], UPLOADED_FILE.name));
      const request = http.expectOne('/api/backups/upload/');
      request.event({ type: HttpEventType.UploadProgress, loaded: 4, total: 4 });
      harness.detectChanges();

      const progress = element().querySelector('mat-progress-bar');
      expect(progress?.hasAttribute('aria-valuenow')).toBe(false);
      expect(element().querySelector('.backups__upload-status')?.textContent).toContain('Saving the file…');
      expect(element().querySelector('.backups__upload button')).toBeNull();

      request.flush(UPLOADED_FILE, { status: 201, statusText: 'Created' });
      harness.detectChanges();
      expect(element().querySelector('mat-progress-bar')).toBeNull();
      TestBed.tick();
      listRequest().flush(pageOf([UPLOADED_FILE, FILE]));
      await settle();
    });
  });

  describe('plans', () => {
    it('says what each plan does, how it last ran and when it runs next', async () => {
      await showWith([FILE], 1, [PLAN, { ...MANUAL_PLAN, enabled: false }]);

      const [daily, manual] = planRows();
      expect(daily.textContent).toContain('django-dbs');
      expect(daily.textContent).toContain('Daily');
      expect(daily.textContent).toContain('Here: 7');
      expect(daily.textContent).toContain('On the server: 1');
      expect(daily.textContent).toContain('Succeeded');
      expect(daily.querySelectorAll('time').length).toBe(2);

      expect(manual.textContent).toContain('Manual');
      expect(manual.textContent).toContain('Disabled');
      expect(manual.textContent).toContain('Failed');
      expect(manual.textContent).toContain('The server did not answer over SSH.');
      expect(manual.querySelectorAll('time').length).toBe(1);
    });

    it('lists the folders a folder plan archives, each read left to right', async () => {
      await showWith([FILE], 1, [PLAN, ARCHIVE_PLAN]);

      const [, media] = planRows();
      expect(media.textContent).toContain('Folders: 2');
      const paths = Array.from(media.querySelectorAll('li bdi'), (path) => [path.textContent, path.getAttribute('dir')]);
      expect(paths).toEqual([
        ['/srv/app/media', 'ltr'],
        ['/srv/app/uploads', 'ltr'],
      ]);
    });

    it('says where a collection reads from, as one path read left to right', async () => {
      await showWith([FILE], 1, [COLLECT_PLAN, { ...COLLECT_PLAN, id: 'trailing', paths: ['/var/backups/'] }]);

      const rows = planRows();
      for (const row of rows) {
        expect(row.textContent).toContain('Existing files');
        expect(row.textContent).toContain('Here: 14');
        expect(row.textContent).not.toContain('On the server');
        const source = row.querySelector('bdi.backups__code');
        expect(source?.getAttribute('dir')).toBe('ltr');
      }
      expect(rows.map((row) => row.querySelector('bdi.backups__code')?.textContent)).toEqual([
        '/var/backups/postgres/*.sql.gz',
        '/var/backups/*.sql.gz',
      ]);
    });

    it('offers a first django-dbs plan when the server has none', async () => {
      const page = await showWith([FILE], 1, []);
      const open = spyOnDialogs();

      const empty = element().querySelector('app-empty-state');
      expect(empty?.textContent).toContain('No plans yet');
      expect(text()).not.toContain('Add plan');
      empty?.querySelector('button')?.click();

      expect(open).toHaveBeenCalledWith(
        PlanForm,
        expect.objectContaining({ data: { plan: null, name: 'django-dbs' } }),
      );

      const [, folders, collect] = Array.from(empty?.querySelectorAll('button') ?? []);
      expect(folders?.textContent?.trim()).toBe('Back up folders');
      folders?.click();
      expect(open).toHaveBeenLastCalledWith(PlanForm, expect.objectContaining({ data: { plan: null, kind: 'archive' } }));

      expect(collect?.textContent?.trim()).toBe('Collect existing files');
      collect?.click();
      expect(open).toHaveBeenLastCalledWith(PlanForm, expect.objectContaining({ data: { plan: null, kind: 'collect' } }));

      // One offer leads; the other two kinds sit a step below it, level with each other.
      const offers = await TestbedHarnessEnvironment.loader(harness.fixture).getAllHarnesses(
        MatButtonHarness.with({ ancestor: 'app-empty-state' }),
      );
      expect(await Promise.all(offers.map((offer) => offer.getAppearance()))).toEqual([
        'filled',
        'outlined',
        'outlined',
      ]);

      page.editPlan(PLAN);
      expect(open).toHaveBeenLastCalledWith(PlanForm, expect.objectContaining({ data: { plan: PLAN } }));
    });

    it('runs a plan from its row and says a backup is running', async () => {
      const page = await showWith([FILE]);

      page.run(PLAN);
      const request = http.expectOne(`/api/backups/plans/${PLAN.id}/run/`);
      request.flush({ activity: JOB_ID });
      harness.detectChanges();

      expect(page.isRunning(PLAN)).toBe(true);
      expect(element().querySelector('app-notice')?.textContent).toContain('A backup is running.');
    });

    it('asks before deleting a plan, saying its backups stay', async () => {
      const page = await showWith([FILE]);
      const ask = vi.spyOn(TestBed.inject(Confirmation), 'ask').mockResolvedValueOnce(false).mockResolvedValueOnce(true);

      await page.removePlan(PLAN);
      expect(ask).toHaveBeenCalledWith(
        expect.objectContaining({
          title: `Delete ⁨${PLAN.name}⁩?`,
          message: 'The plan stops running. Its backups stay listed until someone deletes them.',
          acceptSeverity: 'danger',
        }),
      );
      http.expectNone(`/api/backups/plans/${PLAN.id}/`);

      const removing = page.removePlan(PLAN);
      await vi.waitFor(() => http.expectOne(`/api/backups/plans/${PLAN.id}/`)).then((request) =>
        request.flush(null, { status: 204, statusText: 'No Content' }),
      );
      await removing;
      TestBed.tick();
      plansRequest().flush(pageOf([]));
      await settle();
    });
  });

  it('offers Restore on a django-dbs file only, and opens its form', async () => {
    const page = await showWith([FILE, ARCHIVE_FILE, COLLECTED_FILE, UPLOADED_FILE]);
    const open = spyOnDialogs();

    const restores = Array.from(element().querySelectorAll<HTMLButtonElement>('button[aria-label^="Restore "]'));
    expect(new Set(restores.map((button) => button.getAttribute('aria-label')))).toEqual(new Set([`Restore ${FILE.name}`]));
    restores[0].click();

    expect(open).toHaveBeenCalledWith(RestoreForm, expect.objectContaining({ data: { file: FILE } }));
    expect(page.canRestore(UPLOADED_FILE)).toBe(false);
  });

  it('shows a rehearsal running on its row as rehearsing', async () => {
    const page = await showWith([FILE]);

    const store = harness.routeDebugElement?.injector.get(BackupsStore);
    const starting = store!.restore(FILE, { mode: 'merge', rehearse: true });
    http.expectOne(`/api/backups/${FILE.id}/restore/`).flush({ activity: JOB_ID });
    await starting;
    harness.detectChanges();

    expect(page.restoring(FILE)).toBe('rehearse');
    expect(element().querySelector('button[aria-label^="Restore "]')?.textContent).toContain('Rehearsing…');
  });

  it('starts a backup of the server from its button', async () => {
    const page = await showWith([FILE]);

    page.take();
    const request = http.expectOne('/api/backups/take/');
    expect(request.request.body).toEqual({ server: SERVER_ID });
    request.flush({ activity: JOB_ID });
    harness.detectChanges();

    expect(element().querySelector('app-notice')?.textContent).toContain('A backup is running.');
  });

  it('asks before deleting, and deletes only on yes', async () => {
    const page = await showWith([FILE]);
    const ask = vi.spyOn(TestBed.inject(Confirmation), 'ask').mockResolvedValueOnce(false).mockResolvedValueOnce(true);

    await page.remove(FILE);
    expect(ask).toHaveBeenCalledWith(
      expect.objectContaining({ title: `Delete ⁨${FILE.name}⁩?`, acceptSeverity: 'danger' }),
    );
    http.expectNone(`/api/backups/${FILE.id}/`);

    const removing = page.remove(FILE);
    await vi.waitFor(() => http.expectOne(`/api/backups/${FILE.id}/`)).then((request) =>
      request.flush(null, { status: 204, statusText: 'No Content' }),
    );
    await removing;
    TestBed.tick();
    listRequest().flush(pageOf([]));
    await settle();
    harness.detectChanges();

    const deleted = element().querySelector('app-notice');
    expect(deleted?.textContent).toContain('Backup deleted.');
    expect(deleted?.textContent).toContain(FILE.name);
    const undo = Array.from(deleted?.querySelectorAll('button') ?? []).find(
      (button) => button.textContent?.trim() === 'Undo',
    );
    undo?.click();
    http.expectOne(`/api/backups/${FILE.id}/undo-delete/`).flush(FILE);
    const reload = await vi.waitFor(() => listRequest());
    reload.flush(pageOf([FILE]));
    await settle();
  });

  it('writes each size the way a reader says it', async () => {
    await showWith([FILE]);

    expect(element().querySelector('.backups__size')?.textContent?.trim()).toBe('1.2 MB');
  });
});
