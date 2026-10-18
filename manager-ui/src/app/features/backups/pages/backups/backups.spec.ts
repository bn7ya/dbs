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
import { MASTER, OPERATOR } from '@core/auth/testing/identity.fixtures';
import { errorInterceptor } from '@core/http/error.interceptor';
import { JobWatcher } from '@core/jobs/job-watcher';
import { Dialogs } from '@shared/dialogs/dialogs';
import type { DialogHandle } from '@shared/dialogs/dialogs.types';
import { Downloader } from '@shared/downloader/downloader';
import { PasswordPrompt } from '@shared/password-prompt/password-prompt';
import type { PasswordPromptData } from '@shared/password-prompt/password-prompt.types';
import { Toaster } from '@shared/toaster/toaster';
import { RestoreForm } from '../../components/restore-form/restore-form';
import type { BackupFile } from '../../data/backups.types';
import {
  APPLICATION_ID,
  ARCHIVE_FILE,
  COLLECTED_FILE,
  FILE,
  JOB_ID,
  PLAN,
  QUARANTINED,
  UPLOADED_FILE,
  VERIFIED,
  pageOf,
} from '../../testing/backups.fixtures';
import { BackupsStore } from '../../state/backups.store';
import { BackupsPage } from './backups';

const ROUTES: Routes = [
  {
    path: 'applications/:applicationId',
    children: [{ path: 'backups', loadChildren: () => import('../../backups.routes').then((m) => m.routes) }],
  },
];

describe('BackupsPage', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const listRequest = (): TestRequest => http.expectOne((request) => request.url === '/api/backups/');

  const answerJobs = (): void => {
    for (const request of http.match((each) => each.url === '/api/activity/')) {
      request.flush(pageOf([]));
    }
  };

  const show = async (identity: Identity = MASTER): Promise<BackupsPage> => {
    harness = await RouterTestingHarness.create();
    const navigating = harness.navigateByUrl(`/applications/${APPLICATION_ID}/backups`, BackupsPage);
    const me = await vi.waitFor(() => http.expectOne('/api/auth/me/'));
    me.flush(identity);
    const page = await navigating;
    TestBed.tick();
    return page;
  };

  const showWith = async (results: readonly BackupFile[], count = results.length, identity?: Identity) => {
    const page = await show(identity);
    listRequest().flush(pageOf(results, count));
    answerJobs();
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

  const promptOf = (open: ReturnType<typeof spyOnDialogs>): PasswordPromptData => {
    const [component, options] = open.mock.calls[0];
    expect(component).toBe(PasswordPrompt);
    return options.data as PasswordPromptData;
  };

  const refusedFor = (code: string) =>
    [{ error: { code, message: 'Server prose' } }, { status: 400, statusText: 'Bad Request' }] as const;

  const fileRows = (): HTMLTableRowElement[] =>
    Array.from(element().querySelectorAll<HTMLTableRowElement>('table tr[mat-row]'));

  const button = (label: string): HTMLButtonElement | undefined =>
    Array.from(element().querySelectorAll('button')).find((each) => each.textContent?.trim() === label);

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

  it("lists the route's application under a second-level title, with a link to download each file", async () => {
    const page = await show();

    expect(page.applicationId()).toBe(APPLICATION_ID);
    const request = listRequest();
    expect(request.request.params.get('application')).toBe(APPLICATION_ID);
    request.flush(pageOf([FILE, VERIFIED]));
    answerJobs();
    await settle();
    harness.detectChanges();

    expect(element().querySelector('h1')).toBeNull();
    expect(Array.from(element().querySelectorAll('h2'), (heading) => heading.textContent?.trim())).toEqual(['Backups']);
    expect(element().querySelector('table')?.getAttribute('aria-label')).toBe('Backups');
    const headers = Array.from(element().querySelectorAll('th'), (header) => header.textContent?.trim());
    expect(headers).toEqual(['Name', 'Taken', 'Plan', 'Size', 'Check', 'Actions']);
    expect(text()).toContain(FILE.name);
    const download = element().querySelector<HTMLAnchorElement>(`a[href="/api/backups/${FILE.id}/download/"]`);
    expect(download?.getAttribute('download')).toBe(FILE.name);
    expect(download?.getAttribute('aria-label')).toBe(`Download ${FILE.name}`);
  });

  it('downloads a sealed file through the password, and a django-dbs backup straight from its link', async () => {
    await showWith([FILE, ARCHIVE_FILE, UPLOADED_FILE]);
    const started = vi.spyOn(TestBed.inject(Downloader), 'start').mockReturnValue(undefined);
    const open = spyOnDialogs();

    const links = Array.from(element().querySelectorAll<HTMLAnchorElement>('a[href*="/download/"]'));
    expect(links.map((link) => link.getAttribute('aria-label'))).toEqual([`Download ${FILE.name}`]);
    const buttons = Array.from(element().querySelectorAll<HTMLButtonElement>('button[aria-label^="Download "]'));
    expect(buttons.map((each) => each.getAttribute('aria-label'))).toEqual([
      `Download ${ARCHIVE_FILE.name}`,
      `Download ${UPLOADED_FILE.name}`,
    ]);

    buttons[0].click();
    await vi.waitFor(() => expect(open).toHaveBeenCalledOnce());
    const prompt = promptOf(open);
    expect(prompt.titleKey).toBe('backups.download.prompt.title');

    const refusing = prompt.submit('wrong');
    http.expectOne(`/api/backups/${ARCHIVE_FILE.id}/download/`).flush(...refusedFor('invalid_password'));
    await expect(refusing).resolves.toBe(false);
    expect(started).not.toHaveBeenCalled();

    const linking = prompt.submit('hunter2');
    const request = http.expectOne(`/api/backups/${ARCHIVE_FILE.id}/download/`);
    expect(request.request.body).toEqual({ account_password: 'hunter2' });
    request.flush({ url: `/api/backups/${ARCHIVE_FILE.id}/download/?ticket=t1` });
    await expect(linking).resolves.toBe(true);
    expect(started).toHaveBeenCalledWith(`/api/backups/${ARCHIVE_FILE.id}/download/?ticket=t1`);
  });

  it('leaves the pages out while one page holds every file', async () => {
    await showWith([FILE], 20);
    expect(element().querySelector('mat-paginator')).toBeNull();
  });

  it('pages a list longer than one page, in a labelled navigation', async () => {
    await showWith([FILE], 21);
    expect(element().querySelector('nav mat-paginator')).not.toBeNull();
    expect(element().querySelector('nav')?.getAttribute('aria-label')).toBe('Backup pages');
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

  it('shows a quarantined file as failed with its reason, and never offers to restore it', async () => {
    await showWith([QUARANTINED]);

    expect(element().querySelector('button[aria-label^="Restore "]')).toBeNull();
    expect(text()).toContain('Quarantined');
    expect(text()).toContain(QUARANTINED.failure);
  });

  it('offers Restore on a django-dbs file only, and opens its form', async () => {
    await showWith([FILE, ARCHIVE_FILE, COLLECTED_FILE, UPLOADED_FILE]);
    const open = spyOnDialogs();

    const restores = Array.from(element().querySelectorAll<HTMLButtonElement>('button[aria-label^="Restore "]'));
    expect(restores.map((each) => each.getAttribute('aria-label'))).toEqual([`Restore ${FILE.name}`]);
    restores[0].click();

    expect(open).toHaveBeenCalledWith(RestoreForm, expect.objectContaining({ data: { file: FILE } }));
  });

  it('shows a rehearsal running on its row as rehearsing', async () => {
    await showWith([FILE]);

    const store = harness.routeDebugElement?.injector.get(BackupsStore);
    const starting = store!.restore(FILE, { mode: 'merge', rehearse: true });
    http.expectOne(`/api/backups/${FILE.id}/restore/`).flush({ activity: JOB_ID });
    await starting;
    harness.detectChanges();

    const restore = element().querySelector<HTMLButtonElement>('button[aria-label^="Restore "]');
    expect(restore?.textContent).toContain('Rehearsing…');
    expect(restore?.disabled).toBe(true);
  });

  it('starts a backup of the application from its one filled button, and says a backup is running', async () => {
    await showWith([FILE]);

    const filled = await TestbedHarnessEnvironment.loader(harness.fixture).getAllHarnesses(
      MatButtonHarness.with({ appearance: 'filled' }),
    );
    expect(await Promise.all(filled.map((each) => each.getText()))).toEqual(['Back up now']);
    await filled[0].click();
    const request = http.expectOne('/api/backups/take/');
    expect(request.request.body).toEqual({ application: APPLICATION_ID });
    request.flush({ activity: JOB_ID });
    harness.detectChanges();

    expect(element().querySelector('app-notice')?.textContent).toContain('A backup is running.');
    expect(button('Backing up…')?.disabled).toBe(true);
  });

  it('leaves out what an operator may not do', async () => {
    await showWith([FILE, ARCHIVE_FILE], 2, OPERATOR);

    expect(button('Upload a backup')).toBeUndefined();
    expect(button('Back up now')).not.toBeUndefined();
    expect(element().querySelector('button[aria-label^="Delete "]')).toBeNull();
    expect(element().querySelector('button[aria-label^="Verify "]')).not.toBeNull();
    expect(element().querySelector('button[aria-label^="Restore "]')).not.toBeNull();
  });

  it('asks for the password before deleting, keeps a wrong one in the prompt, and deletes with the right one', async () => {
    await showWith([FILE]);
    const open = spyOnDialogs();

    element().querySelector<HTMLButtonElement>(`button[aria-label="Delete ${FILE.name}"]`)?.click();
    await vi.waitFor(() => expect(open).toHaveBeenCalledOnce());
    const prompt = promptOf(open);
    expect(prompt).toMatchObject({
      titleKey: 'backups.delete.prompt.title',
      bodyValues: { name: `⁨${FILE.name}⁩` },
      submitKey: 'actions.delete',
      destructive: true,
    });
    http.expectNone(`/api/backups/${FILE.id}/`);

    const refusing = prompt.submit('wrong');
    http.expectOne(`/api/backups/${FILE.id}/`).flush(...refusedFor('invalid_password'));
    await expect(refusing).resolves.toBe(false);
    expect(prompt.error()?.code).toBe('invalid_password');

    const removing = prompt.submit('hunter2');
    const request = http.expectOne(`/api/backups/${FILE.id}/`);
    expect(request.request.method).toBe('DELETE');
    request.flush(null, { status: 204, statusText: 'No Content' });
    await expect(removing).resolves.toBe(true);
    TestBed.tick();
    listRequest().flush(pageOf([]));
    await settle();
    harness.detectChanges();

    const deleted = element().querySelector('app-notice');
    expect(deleted?.textContent).toContain('Backup deleted.');
    expect(deleted?.textContent).toContain(FILE.name);
    const undo = Array.from(deleted?.querySelectorAll('button') ?? []).find(
      (each) => each.textContent?.trim() === 'Undo',
    );
    undo?.click();
    http.expectOne(`/api/backups/${FILE.id}/undo-delete/`).flush(FILE);
    const reload = await vi.waitFor(() => listRequest());
    reload.flush(pageOf([FILE]));
    await settle();
  });

  it('writes each size the way a reader says it', async () => {
    await showWith([FILE]);

    expect(element().querySelector('.backup-table__size')?.textContent?.trim()).toBe('1.2 MB');
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

    it('opens the hidden picker from its outlined button', async () => {
      await showWith([FILE]);
      const opened = vi.spyOn(picker(), 'click').mockImplementation(() => undefined);

      expect(picker().hidden).toBe(true);
      const upload = await TestbedHarnessEnvironment.loader(harness.fixture).getHarness(
        MatButtonHarness.with({ text: 'Upload a backup' }),
      );
      expect(await upload.getAppearance()).toBe('outlined');
      button('Upload a backup')?.click();

      expect(opened).toHaveBeenCalledOnce();
    });

    it('shows the file on its way, read left to right, with its share sent and a way to cancel it', async () => {
      await showWith([FILE]);
      choose(new File(['abcd'], UPLOADED_FILE.name));
      const request = http.expectOne('/api/backups/upload/');
      request.event({ type: HttpEventType.UploadProgress, loaded: 1, total: 4 });
      harness.detectChanges();

      expect(picker().value).toBe('');
      expect(element().querySelector('mat-progress-bar')?.getAttribute('aria-valuenow')).toBe('25');
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
      expect(document.activeElement).toBe(button('Upload a backup'));
    });

    it('says the file is being saved once every byte is sent, with nothing left to cancel', async () => {
      await showWith([FILE]);
      choose(new File(['abcd'], UPLOADED_FILE.name));
      const request = http.expectOne('/api/backups/upload/');
      request.event({ type: HttpEventType.UploadProgress, loaded: 4, total: 4 });
      harness.detectChanges();

      expect(element().querySelector('mat-progress-bar')?.hasAttribute('aria-valuenow')).toBe(false);
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
});
