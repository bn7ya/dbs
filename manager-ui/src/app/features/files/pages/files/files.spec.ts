import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, type TestRequest } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter, withComponentInputBinding, type Routes } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { ConfirmationService, MessageService } from 'primeng/api';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Identity } from '@core/auth/data/auth.types';
import { errorInterceptor } from '@core/http/error.interceptor';
import { Confirmation } from '@shared/confirm/confirmation';
import { Dialogs } from '@shared/dialogs/dialogs';
import type { DialogHandle } from '@shared/dialogs/dialogs.types';
import { Toaster } from '@shared/toaster/toaster';
import { NewFolderDialog } from '../../components/new-folder/new-folder';
import type { Entry, Listing } from '../../data/files.types';
import { FILE, FOLDER, LINK, NESTED, OTHER, OTHER_ROOT, ROOT, SERVER_ID, listingOf } from '../../testing/files.fixtures';
import { FilesPage } from './files';

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
    children: [{ path: 'files', loadChildren: () => import('../../files.routes').then((m) => m.routes) }],
  },
];

const ltr = (text: string): string => `⁦${text}⁩`;

describe('FilesPage', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const listRequest = (): TestRequest =>
    http.expectOne((request) => request.url === `/api/files/${SERVER_ID}/` && request.method === 'GET');

  const showWith = async (listing: Listing, query = ''): Promise<FilesPage> => {
    harness = await RouterTestingHarness.create();
    const navigating = harness.navigateByUrl(`/servers/${SERVER_ID}/files${query}`, FilesPage);
    const me = await vi.waitFor(() => http.expectOne('/api/auth/me/'));
    me.flush(IDENTITY);
    const page = await navigating;
    TestBed.tick();
    listRequest().flush(listing);
    await settle();
    harness.detectChanges();
    return page;
  };

  const answer = async (listing: Listing): Promise<TestRequest> => {
    const request = await vi.waitFor(() => listRequest());
    request.flush(listing);
    await settle();
    harness.detectChanges();
    return request;
  };

  const element = (): HTMLElement => harness.routeNativeElement as HTMLElement;
  const rows = (): HTMLElement[] => Array.from(element().querySelectorAll<HTMLElement>('p-table tbody tr'));
  const buttonNamed = (text: string): HTMLButtonElement | undefined =>
    Array.from(element().querySelectorAll('button')).find((button) => button.textContent?.trim() === text);

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter(ROUTES, withComponentInputBinding()),
        MessageService,
        ConfirmationService,
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

  it("lists the server's first allowed folder under a second-level title", async () => {
    const page = await showWith(listingOf([FOLDER, FILE, LINK, OTHER], { roots: [ROOT] }));

    expect(page.serverId()).toBe(SERVER_ID);
    expect(element().querySelector('h1')).toBeNull();
    expect(element().querySelector('h2')?.textContent?.trim()).toBe('Files');
    expect(rows().map((row) => row.querySelector('bdi')?.textContent)).toEqual([
      FOLDER.name,
      FILE.name,
      LINK.name,
      OTHER.name,
    ]);
    // One allowed folder: nothing to pick between.
    expect(element().querySelector('p-select')).toBeNull();
  });

  it('opens a folder from its row, by link, and lists it', async () => {
    await showWith(listingOf([FOLDER, FILE]));

    const open = rows()[0].querySelector<HTMLAnchorElement>('a');
    expect(open?.getAttribute('aria-label')).toBe(`Open folder ${FOLDER.name}`);
    expect(open?.getAttribute('href')).toBe(`/servers/${SERVER_ID}/files?path=${encodeURIComponent(FOLDER.path)}`);
    open?.click();

    const request = await answer(listingOf([NESTED], { path: FOLDER.path }));
    expect(request.request.params.get('path')).toBe(FOLDER.path);
    expect(TestBed.inject(Router).url).toBe(`/servers/${SERVER_ID}/files?path=${encodeURIComponent(FOLDER.path)}`);
    expect(rows().map((row) => row.querySelector('bdi')?.textContent)).toEqual([NESTED.name]);
  });

  it('shows a size for a file and a dash for a folder, and a kind under what does not open', async () => {
    await showWith(listingOf([FOLDER, FILE, LINK, OTHER]));

    const [folder, file, link, other] = rows();
    expect(folder.textContent).toContain('—');
    expect(file.querySelector('.files__size')?.textContent?.trim()).toBe('1.2 MB');
    expect(file.querySelector('p-tag')).toBeNull();
    expect(link.querySelector('p-tag')?.textContent?.trim()).toBe('Link');
    expect(other.querySelector('p-tag')?.textContent?.trim()).toBe('Special file');
    expect(link.querySelector('a[aria-label^="Open folder"]')).toBeNull();
  });

  it('offers a download for a file only, pointed at its path', async () => {
    await showWith(listingOf([FOLDER, FILE, LINK]));

    const downloads = rows().flatMap((row) => Array.from(row.querySelectorAll<HTMLAnchorElement>('a[download]')));
    expect(downloads).toHaveLength(1);
    expect(downloads[0].getAttribute('href')).toBe(
      `/api/files/${SERVER_ID}/download/?path=${encodeURIComponent(FILE.path)}`,
    );
    expect(downloads[0].getAttribute('download')).toBe(FILE.name);
    expect(downloads[0].getAttribute('aria-label')).toBe(`Download ${FILE.name}`);
  });

  describe('the way back up', () => {
    it('is a breadcrumb from the allowed folder, each name in its own direction, with the folder on screen last', async () => {
      await showWith(listingOf([NESTED], { path: FOLDER.path }), `?path=${encodeURIComponent(FOLDER.path)}`);

      const trail = element().querySelector('p-breadcrumb nav');
      expect(trail?.getAttribute('aria-label')).toBe('Folder path');
      const crumbs = Array.from(trail?.querySelectorAll('.p-breadcrumb-item-link') ?? []);
      expect(crumbs.map((crumb) => crumb.textContent?.trim())).toEqual([ROOT, 'photos']);
      expect(crumbs.map((crumb) => crumb.querySelector('bdi')?.getAttribute('dir'))).toEqual(['auto', 'auto']);
      expect(crumbs[1].getAttribute('aria-current')).toBe('page');
    });

    it('goes up to the folder a crumb names', async () => {
      await showWith(listingOf([NESTED], { path: FOLDER.path }), `?path=${encodeURIComponent(FOLDER.path)}`);

      element().querySelector<HTMLAnchorElement>('p-breadcrumb a.p-breadcrumb-item-link')?.click();

      const request = await answer(listingOf([FOLDER, FILE]));
      expect(request.request.params.get('path')).toBe(ROOT);
      expect(TestBed.inject(Router).url).toBe(`/servers/${SERVER_ID}/files?path=${encodeURIComponent(ROOT)}`);
    });

    it('puts focus on the place once the link that opened a folder is gone', async () => {
      await showWith(listingOf([FOLDER, FILE]));

      const open = rows()[0].querySelector<HTMLAnchorElement>('a');
      open?.focus();
      open?.click();
      await answer(listingOf([NESTED], { path: FOLDER.path }));

      expect(document.activeElement).toBe(element().querySelector('.files__location'));
    });
  });

  it('lets the reader pick between allowed folders when there is more than one', async () => {
    const page = await showWith(listingOf([FOLDER, FILE]));

    expect(element().querySelector('p-select')).not.toBeNull();
    expect(page.rootOptions()).toEqual([ROOT, OTHER_ROOT]);

    page.onRoot(OTHER_ROOT);

    const request = await answer(listingOf([], { path: OTHER_ROOT }));
    expect(request.request.params.get('path')).toBe(OTHER_ROOT);
  });

  it('says the folder is empty', async () => {
    await showWith(listingOf([]));
    expect(element().querySelector('app-empty-state')?.textContent).toContain('This folder is empty');
  });

  it("sends a server with no allowed folders to its overview, with nothing to upload into", async () => {
    harness = await RouterTestingHarness.create();
    const navigating = harness.navigateByUrl(`/servers/${SERVER_ID}/files`, FilesPage);
    (await vi.waitFor(() => http.expectOne('/api/auth/me/'))).flush(IDENTITY);
    await navigating;
    TestBed.tick();
    listRequest().flush(
      { error: { code: 'no_allowed_folders', message: 'Server prose' } },
      { status: 400, statusText: 'Bad Request' },
    );
    await settle();
    harness.detectChanges();

    const empty = element().querySelector('app-empty-state');
    expect(empty?.textContent).toContain('No allowed folders');
    expect(empty?.querySelector('a')?.getAttribute('href')).toBe(`/servers/${SERVER_ID}`);
    expect(element().querySelector('p-message')).toBeNull();
    expect(buttonNamed('Upload a file')).toBeUndefined();
    expect(buttonNamed('New folder')).toBeUndefined();
  });

  it('says why a folder could not be listed, and tries again', async () => {
    harness = await RouterTestingHarness.create();
    const navigating = harness.navigateByUrl(`/servers/${SERVER_ID}/files?path=%2Fetc`, FilesPage);
    (await vi.waitFor(() => http.expectOne('/api/auth/me/'))).flush(IDENTITY);
    await navigating;
    TestBed.tick();
    listRequest().flush(
      { error: { code: 'path_outside_roots', message: 'Server prose' } },
      { status: 403, statusText: 'Forbidden' },
    );
    await settle();
    harness.detectChanges();

    expect(element().querySelector('p-message')?.textContent).toContain(
      "This path is outside the server's allowed folders.",
    );
    // A refusal about the path, not a lost session: the reader stays on the page.
    expect(TestBed.inject(Router).url).toBe(`/servers/${SERVER_ID}/files?path=%2Fetc`);
    expect(buttonNamed('New folder')?.disabled).toBe(true);

    buttonNamed('Try again')?.click();
    await answer(listingOf([FILE]));
    expect(rows()).toHaveLength(1);
  });

  describe('deleting', () => {
    it('asks first, naming the path, and deletes only once the reader agrees', async () => {
      await showWith(listingOf([FOLDER, FILE]));
      const ask = vi.spyOn(TestBed.inject(Confirmation), 'ask').mockResolvedValueOnce(false).mockResolvedValueOnce(true);
      const remove = (): HTMLButtonElement | null =>
        rows()[1].querySelector<HTMLButtonElement>(`button[aria-label="Delete ${FILE.name}"]`);

      remove()?.click();
      await vi.waitFor(() => expect(ask).toHaveBeenCalledOnce());
      expect(ask.mock.calls[0][0]).toMatchObject({
        title: 'Delete this file?',
        message: ltr(FILE.path),
        detail: 'This cannot be undone.',
        acceptSeverity: 'danger',
      });
      http.expectNone((request) => request.method === 'DELETE');

      remove()?.click();
      const request = await vi.waitFor(() => http.expectOne((each) => each.method === 'DELETE'));
      expect(request.request.params.get('path')).toBe(FILE.path);
      request.flush(null, { status: 204, statusText: 'No Content' });
      await answer(listingOf([FOLDER]));
    });

    it('says only an empty folder can be deleted', async () => {
      await showWith(listingOf([FOLDER]));
      const ask = vi.spyOn(TestBed.inject(Confirmation), 'ask').mockResolvedValue(false);

      rows()[0].querySelector<HTMLButtonElement>(`button[aria-label="Delete ${FOLDER.name}"]`)?.click();

      await vi.waitFor(() => expect(ask).toHaveBeenCalledOnce());
      expect(ask.mock.calls[0][0]).toMatchObject({
        title: 'Delete this folder?',
        detail: 'Only an empty folder can be deleted. This cannot be undone.',
      });
    });
  });

  it('opens the new folder dialog on the folder on screen', async () => {
    await showWith(listingOf([FILE]));
    const open = vi.spyOn(Dialogs.prototype, 'open').mockReturnValue({} as DialogHandle<Entry>);

    buttonNamed('New folder')?.click();

    expect(open).toHaveBeenCalledOnce();
    const [component, config] = open.mock.calls[0];
    expect(component).toBe(NewFolderDialog);
    expect(config).toEqual({ titleKey: 'files.newFolder.title', data: { folder: ROOT }, size: 'sm' });
  });

  it('uploads the chosen file into the folder on screen', async () => {
    await showWith(listingOf([NESTED], { path: FOLDER.path }), `?path=${encodeURIComponent(FOLDER.path)}`);
    const picker = element().querySelector<HTMLInputElement>('input[type="file"]');
    expect(picker?.hidden).toBe(true);
    const chosen = new File(['abc'], 'dog.jpg');
    Object.defineProperty(picker, 'files', {
      value: { 0: chosen, length: 1, item: (index: number) => (index === 0 ? chosen : null) },
      configurable: true,
    });

    picker?.dispatchEvent(new Event('change'));
    harness.detectChanges();

    const request = http.expectOne(`/api/files/${SERVER_ID}/upload/`);
    expect((request.request.body as FormData).get('path')).toBe(FOLDER.path);
    expect(element().querySelector('.files__upload bdi')?.textContent).toBe('dog.jpg');
    request.flush({ ...NESTED, name: 'dog.jpg', path: `${FOLDER.path}/dog.jpg` }, { status: 201, statusText: 'Created' });
    await answer(listingOf([NESTED], { path: FOLDER.path }));
  });
});
