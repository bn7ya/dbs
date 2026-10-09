import { HttpEventType, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, type TestRequest } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { MessageService } from 'primeng/api';
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import { Toaster } from '@shared/toaster/toaster';
import type { ToastMessage } from '@shared/toaster/toaster.types';
import type { Listing } from '../data/files.types';
import ar from '../i18n/ar.json';
import en from '../i18n/en.json';
import { FILE, FOLDER, NESTED, OTHER_ROOT, ROOT, ROOTS, SERVER_ID, listingOf } from '../testing/files.fixtures';
import { FilesStore } from './files.store';

const OTHER_SERVER = '0f3c2b9e-1111-4c4f-9a43-7b1d2f0c0002';

describe('FilesStore', () => {
  let store: FilesStore;
  let http: HttpTestingController;
  let toasts: MockInstance<(message: ToastMessage) => void>;

  const base = (server = SERVER_ID): string => `/api/files/${server}/`;
  const listRequest = (server = SERVER_ID): TestRequest =>
    http.expectOne((request) => request.url === base(server) && request.method === 'GET');

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const look = (): void => {
    store.entries();
    store.trail();
  };

  const showWith = async (listing: Listing, path: string | null = null, server = SERVER_ID): Promise<void> => {
    store.show(server, path);
    TestBed.tick();
    listRequest(server).flush(listing);
    await settle();
    look();
  };

  const answerReload = async (listing: Listing): Promise<void> => {
    TestBed.tick();
    listRequest().flush(listing);
    await settle();
  };

  const lastToast = (): ToastMessage | undefined => toasts.mock.lastCall?.[0];

  const refuse = (request: TestRequest, code: string, status: number, fields?: Record<string, string[]>): void =>
    request.flush(
      { error: { code, message: 'Server prose', ...(fields === undefined ? {} : { fields }) } },
      { status, statusText: 'Refused' },
    );

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [
        FilesStore,
        MessageService,
        // The real interceptor: the store's contract is that it only ever sees an ApiError.
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    TestBed.inject(LocaleStore).register({ en, ar });
    store = TestBed.inject(FilesStore);
    http = TestBed.inject(HttpTestingController);
    toasts = vi.spyOn(TestBed.inject(Toaster), 'add').mockReturnValue(undefined);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  describe('the listing', () => {
    it('loads nothing until the page shows a folder', () => {
      TestBed.tick();

      http.expectNone(() => true);
      expect(store.entries()).toEqual([]);
      expect(store.pending()).toBe(false);
      expect(store.trail()).toEqual([]);
    });

    it('lists the first allowed folder when none is asked for, with the way to it and every root', async () => {
      store.show(SERVER_ID, null);
      TestBed.tick();
      expect(store.pending()).toBe(true);
      expect(store.current()).toBeNull();

      const request = listRequest();
      expect(request.request.params.has('path')).toBe(false);
      expect(request.request.params.get('page')).toBe('1');
      expect(request.request.params.get('page_size')).toBe('50');
      request.flush(listingOf([FOLDER, FILE]));
      await settle();

      expect(store.entries()).toEqual([FOLDER, FILE]);
      expect(store.current()).toBe(ROOT);
      expect(store.root()).toBe(ROOT);
      expect(store.roots()).toEqual(ROOTS);
      expect(store.trail()).toEqual([{ path: ROOT, name: ROOT }]);
      expect(store.pending()).toBe(false);
      expect(store.empty()).toBe(false);
    });

    it('keeps the rows on screen while another page of the same folder loads', async () => {
      await showWith(listingOf([FOLDER, FILE], { count: 120 }));

      store.goToPage(1, 50);
      TestBed.tick();
      const next = listRequest();
      expect(next.request.params.get('page')).toBe('2');
      expect(store.entries()).toEqual([FOLDER, FILE]);
      next.flush(listingOf([NESTED], { count: 120 }));
      await settle();

      expect(store.entries()).toEqual([NESTED]);
    });

    it('drops the rows of the folder it leaves, and shows the way to the next one before it arrives', async () => {
      await showWith(listingOf([FOLDER, FILE], { count: 120 }));
      store.goToPage(2, 50);
      TestBed.tick();
      listRequest().flush(listingOf([FILE], { count: 120 }));
      await settle();
      look();

      store.show(SERVER_ID, FOLDER.path);
      TestBed.tick();
      const request = listRequest();
      expect(request.request.params.get('path')).toBe(FOLDER.path);
      expect(request.request.params.get('page')).toBe('1');
      expect(store.entries()).toEqual([]);
      expect(store.pending()).toBe(true);
      expect(store.current()).toBeNull();
      expect(store.trail().map((crumb) => crumb.name)).toEqual([ROOT, 'photos']);
      expect(store.roots()).toEqual(ROOTS);

      request.flush(listingOf([NESTED], { path: FOLDER.path }));
      await settle();
      expect(store.entries()).toEqual([NESTED]);
      expect(store.current()).toBe(FOLDER.path);
    });

    it("forgets one server's roots on another's tab", async () => {
      await showWith(listingOf([FILE]));

      store.show(OTHER_SERVER, null);
      TestBed.tick();
      expect(store.roots()).toEqual([]);
      expect(store.trail()).toEqual([]);
      listRequest(OTHER_SERVER).flush(listingOf([], { path: OTHER_ROOT, roots: [OTHER_ROOT] }));
      await settle();

      expect(store.roots()).toEqual([OTHER_ROOT]);
      expect(store.empty()).toBe(true);
    });

    it('says when the server has no allowed folders', async () => {
      store.show(SERVER_ID, null);
      TestBed.tick();
      refuse(listRequest(), 'no_allowed_folders', 400);
      await settle();

      expect(store.noFolders()).toBe(true);
      expect(store.error()?.code).toBe('no_allowed_folders');
    });

    it('holds any other failure as an ApiError, and retries on reload', async () => {
      store.show(SERVER_ID, '/etc');
      TestBed.tick();
      refuse(listRequest(), 'path_outside_roots', 403);
      await settle();
      expect(store.error()?.code).toBe('path_outside_roots');
      expect(store.noFolders()).toBe(false);

      store.reload();
      await answerReload(listingOf([FILE]));
      expect(store.error()).toBeNull();
      expect(store.entries()).toEqual([FILE]);
    });

    it('forgets the rows when the page closes', async () => {
      await showWith(listingOf([FILE]));

      store.close();
      TestBed.tick();

      expect(store.entries()).toEqual([]);
    });

    it('points a download at the file on the server on screen', async () => {
      await showWith(listingOf([FILE]));

      expect(store.downloadUrl(FILE)).toBe(`${base()}download/?path=${encodeURIComponent(FILE.path)}`);
    });
  });

  describe('uploading a file', () => {
    const chosen = (): File => new File(['abc'], FILE.name);
    const uploadRequest = (): TestRequest => http.expectOne(`${base()}upload/`);

    it('reports the share sent, then reloads the folder and names the file', async () => {
      await showWith(listingOf([]));

      store.uploadFile(ROOT, chosen());
      expect(store.uploading()).toBe(true);
      expect(store.uploadProgress()).toBe(0);
      const request = uploadRequest();
      expect((request.request.body as FormData).get('path')).toBe(ROOT);

      request.event({ type: HttpEventType.UploadProgress, loaded: 1, total: 3 });
      expect(store.uploadProgress()).toBe(33);
      request.event({ type: HttpEventType.UploadProgress, loaded: 3, total: 3 });
      expect(store.uploadProgress()).toBeNull();
      expect(store.uploading()).toBe(true);

      request.flush(FILE, { status: 201, statusText: 'Created' });
      expect(store.uploading()).toBe(false);
      expect(lastToast()).toEqual({ severity: 'success', summary: 'File uploaded.', detail: `⁨${FILE.name}⁩` });
      await answerReload(listingOf([FILE]));
      expect(store.entries()).toEqual([FILE]);
    });

    it('leaves the listing alone when the reader has opened another folder meanwhile', async () => {
      await showWith(listingOf([FOLDER]));
      store.uploadFile(ROOT, chosen());
      const request = uploadRequest();
      await showWith(listingOf([], { path: FOLDER.path }), FOLDER.path);

      request.flush(FILE, { status: 201, statusText: 'Created' });
      TestBed.tick();

      http.expectNone((each) => each.url === base() && each.method === 'GET');
      expect(lastToast()?.summary).toBe('File uploaded.');
    });

    it('aborts the request on cancel, says nothing, and can upload again', async () => {
      await showWith(listingOf([FILE]));
      store.uploadFile(ROOT, chosen());
      const request = uploadRequest();

      store.cancelUpload();

      expect(request.cancelled).toBe(true);
      expect(store.uploading()).toBe(false);
      expect(toasts).not.toHaveBeenCalled();

      store.uploadFile(ROOT, chosen());
      uploadRequest().flush(FILE, { status: 201, statusText: 'Created' });
      await answerReload(listingOf([FILE]));
    });

    it('uploads one file to a server at a time', async () => {
      await showWith(listingOf([FILE]));
      store.uploadFile(ROOT, chosen());
      store.uploadFile(ROOT, chosen());

      const request = uploadRequest();
      request.flush(FILE, { status: 201, statusText: 'Created' });
      await answerReload(listingOf([FILE]));
    });

    it('says why it failed, naming the file', async () => {
      await showWith(listingOf([FILE]));

      store.uploadFile(ROOT, chosen());
      refuse(uploadRequest(), 'file_exists', 409);
      expect(store.uploading()).toBe(false);
      expect(lastToast()).toEqual({
        severity: 'danger',
        summary: 'A file or folder with this name already exists here.',
        detail: `⁨${FILE.name}⁩`,
      });

      store.uploadFile(ROOT, chosen());
      uploadRequest().flush('<html>413 Request Entity Too Large</html>', { status: 413, statusText: 'Too Large' });
      expect(lastToast()?.summary).toBe('The file is too large to upload.');

      store.uploadFile(ROOT, chosen());
      refuse(uploadRequest(), 'invalid', 400, { file: ['empty'] });
      expect(lastToast()?.summary).toBe('The file is empty.');
    });
  });

  describe('a new folder', () => {
    it('creates it in the folder given, then reloads the folder and says so', async () => {
      await showWith(listingOf([FILE]));

      const creating = store.createFolder(ROOT, 'photos');
      expect(store.creating()).toBe(true);
      const request = http.expectOne(`${base()}folders/`);
      expect(request.request.body).toEqual({ path: ROOT, name: 'photos' });
      request.flush(FOLDER, { status: 201, statusText: 'Created' });

      await expect(creating).resolves.toEqual(FOLDER);
      expect(store.creating()).toBe(false);
      expect(lastToast()).toEqual({ severity: 'success', summary: 'Folder created.', detail: '⁨photos⁩' });
      await answerReload(listingOf([FOLDER, FILE]));
      expect(store.entries()).toEqual([FOLDER, FILE]);
    });

    it('holds a refusal for the dialog, and clears it for the next one', async () => {
      await showWith(listingOf([FOLDER]));

      const creating = store.createFolder(ROOT, 'photos');
      refuse(http.expectOne(`${base()}folders/`), 'file_exists', 409);

      await expect(creating).resolves.toBeNull();
      expect(store.createError()?.code).toBe('file_exists');
      expect(toasts).not.toHaveBeenCalled();

      store.resetNewFolder();
      expect(store.createError()).toBeNull();
    });
  });

  describe('deleting', () => {
    const deleteRequest = (): TestRequest =>
      http.expectOne((request) => request.url === base() && request.method === 'DELETE');

    it('marks the entry busy, deletes it by path, then reloads and says so', async () => {
      await showWith(listingOf([FOLDER, FILE]));

      const removing = store.remove(FILE);
      expect(store.isDeleting(FILE)).toBe(true);
      expect(store.isDeleting(FOLDER)).toBe(false);
      const request = deleteRequest();
      expect(request.request.params.get('path')).toBe(FILE.path);
      request.flush(null, { status: 204, statusText: 'No Content' });

      await expect(removing).resolves.toBe(true);
      expect(store.isDeleting(FILE)).toBe(false);
      expect(lastToast()).toEqual({ severity: 'success', summary: 'File deleted.', detail: `⁨${FILE.name}⁩` });
      await answerReload(listingOf([FOLDER]));
    });

    it('says a folder was deleted as a folder', async () => {
      await showWith(listingOf([FOLDER, FILE]));

      const removing = store.remove(FOLDER);
      deleteRequest().flush(null, { status: 204, statusText: 'No Content' });
      await removing;

      expect(lastToast()?.summary).toBe('Folder deleted.');
      await answerReload(listingOf([FILE]));
    });

    it('says why a folder was not deleted, and changes nothing', async () => {
      await showWith(listingOf([FOLDER]));

      const removing = store.remove(FOLDER);
      refuse(deleteRequest(), 'folder_not_empty', 409);

      await expect(removing).resolves.toBe(false);
      expect(lastToast()).toEqual({
        severity: 'danger',
        summary: 'The folder is not empty. Only an empty folder can be deleted.',
        detail: '⁨photos⁩',
      });
      TestBed.tick();
      http.expectNone((each) => each.method === 'GET');
    });

    it('steps back a page when the only entry of the last one is gone', async () => {
      await showWith(listingOf([FOLDER, FILE], { count: 51 }));
      store.goToPage(1, 50);
      TestBed.tick();
      listRequest().flush(listingOf([NESTED], { count: 51 }));
      await settle();
      look();

      const removing = store.remove(NESTED);
      deleteRequest().flush(null, { status: 204, statusText: 'No Content' });
      await removing;
      TestBed.tick();

      const request = listRequest();
      expect(request.request.params.get('page')).toBe('1');
      request.flush(listingOf([FOLDER, FILE], { count: 50 }));
      await settle();
      expect(store.page()).toBe(0);
    });
  });
});
