import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, type TestRequest } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { MessageService } from 'primeng/api';
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';

import type { Page } from '@core/http/api.types';
import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import { Toaster } from '@shared/toaster/toaster';
import type { ToastMessage } from '@shared/toaster/toaster.types';
import type { EnvVersion } from '../data/envfiles.types';
import ar from '../i18n/ar.json';
import en from '../i18n/en.json';
import {
  COMPARISON,
  CONTENT,
  ENV_PATH,
  OLDER,
  OLDEST,
  SERVER_ID,
  VERSION,
  pageOf,
} from '../testing/envfiles.fixtures';
import { EnvfilesStore } from './envfiles.store';

const OTHER_SERVER = '0f3c2b9e-1111-4c4f-9a43-7b1d2f0c0002';

const PULLED: EnvVersion = { ...VERSION, id: '7a1e4c20-5555-4d3b-8c9f-1e2d3c4b0004', created_at: '2026-10-01T08:00:00Z' };

describe('EnvfilesStore', () => {
  let store: EnvfilesStore;
  let http: HttpTestingController;
  let toasts: MockInstance<(message: ToastMessage) => void>;

  const listRequest = (server = SERVER_ID): TestRequest =>
    http.expectOne((request) => request.url === '/api/envfiles/' && request.params.get('server') === server);
  const pathRequest = (server = SERVER_ID): TestRequest => http.expectOne(`/api/servers/${server}/`);

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const openWith = async (page: Page<EnvVersion>, envPath = ENV_PATH, server = SERVER_ID): Promise<void> => {
    store.open(server);
    TestBed.tick();
    pathRequest(server).flush({ id: server, env_path: envPath });
    listRequest(server).flush(page);
    await settle();
    store.versions();
  };

  const answerReload = async (page: Page<EnvVersion>): Promise<TestRequest> => {
    TestBed.tick();
    const request = listRequest();
    request.flush(page);
    await settle();
    return request;
  };

  const refuse = (request: TestRequest, code: string, status: number): void =>
    request.flush({ error: { code, message: 'Server prose' } }, { status, statusText: 'Refused' });

  const lastToast = (): ToastMessage | undefined => toasts.mock.lastCall?.[0];

  const reveal = async (version: EnvVersion): Promise<void> => {
    const revealing = store.reveal(version, 'hunter2');
    http.expectOne(`/api/envfiles/${version.id}/reveal/`).flush({ content: CONTENT });
    await expect(revealing).resolves.toBe(true);
  };

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [
        EnvfilesStore,
        // The real interceptor: the store's contract is that it only ever sees an ApiError.
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
        MessageService,
      ],
    });
    TestBed.inject(LocaleStore).register({ en, ar });
    store = TestBed.inject(EnvfilesStore);
    http = TestBed.inject(HttpTestingController);
    toasts = vi.spyOn(TestBed.inject(Toaster), 'add').mockReturnValue(undefined);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  describe('the versions', () => {
    it('loads nothing until the page opens a server', () => {
      TestBed.tick();

      http.expectNone(() => true);
      expect(store.versions()).toEqual([]);
      expect(store.selected()).toBeNull();
      expect(store.envPath()).toBeNull();
    });

    it('lists the newest first, says where the file is, and selects the newest', async () => {
      store.open(SERVER_ID);
      TestBed.tick();
      expect(store.pending()).toBe(true);

      pathRequest().flush({ id: SERVER_ID, env_path: ENV_PATH });
      const request = listRequest();
      expect(request.request.params.get('page')).toBe('1');
      expect(request.request.params.get('page_size')).toBe('20');
      request.flush(pageOf([VERSION, OLDER, OLDEST]));
      await settle();

      expect(store.envPath()).toBe(ENV_PATH);
      expect(store.noPath()).toBe(false);
      expect(store.versions()).toEqual([VERSION, OLDER, OLDEST]);
      expect(store.selected()).toEqual(VERSION);
      expect(store.hasPrevious()).toBe(true);
      expect(store.empty()).toBe(false);
    });

    it('knows when the server has no .env file set', async () => {
      await openWith(pageOf([]), '');

      expect(store.noPath()).toBe(true);
      expect(store.empty()).toBe(true);
      expect(store.selected()).toBeNull();
    });

    it('selects another version, and knows the oldest has nothing before it', async () => {
      await openWith(pageOf([VERSION, OLDER, OLDEST]));

      store.select(OLDEST);

      expect(store.selected()).toEqual(OLDEST);
      expect(store.hasPrevious()).toBe(false);
    });

    it('knows a version older than the last row of a page is on the next', async () => {
      await openWith(pageOf([VERSION, OLDER], 21));
      store.select(OLDER);

      expect(store.hasPrevious()).toBe(true);
    });

    it("never shows one server's versions on another's tab", async () => {
      await openWith(pageOf([VERSION]));

      store.open(OTHER_SERVER);
      TestBed.tick();

      expect(store.versions()).toEqual([]);
      expect(store.pending()).toBe(true);
      pathRequest(OTHER_SERVER).flush({ id: OTHER_SERVER, env_path: ENV_PATH });
      listRequest(OTHER_SERVER).flush(pageOf([]));
      await settle();
    });
  });

  describe('pull', () => {
    it('keeps a new version, says so, and selects it on the first page', async () => {
      await openWith(pageOf([VERSION, OLDER]));
      store.select(OLDER);

      const pulling = store.pull();
      expect(store.pulling()).toBe(true);
      const request = http.expectOne('/api/envfiles/pull/');
      expect(request.request.body).toEqual({ server: SERVER_ID });
      request.flush({ created: true, version: PULLED });
      await pulling;

      expect(store.pulling()).toBe(false);
      expect(lastToast()).toEqual({ severity: 'success', summary: 'New version kept.' });
      await answerReload(pageOf([PULLED, VERSION, OLDER]));
      expect(store.selected()).toEqual(PULLED);
    });

    it('says nothing changed, and leaves the list and the selection alone', async () => {
      await openWith(pageOf([VERSION, OLDER]));
      store.select(OLDER);

      const pulling = store.pull();
      http.expectOne('/api/envfiles/pull/').flush({ created: false, version: VERSION });
      await pulling;

      expect(lastToast()).toEqual({ severity: 'info', summary: 'No change since the last version.' });
      TestBed.tick();
      http.expectNone((request) => request.url === '/api/envfiles/');
      expect(store.selected()).toEqual(OLDER);
    });

    it('says why the file could not be pulled', async () => {
      await openWith(pageOf([]));

      const pulling = store.pull();
      refuse(http.expectOne('/api/envfiles/pull/'), 'env_too_large', 413);
      await pulling;

      expect(lastToast()).toEqual({ severity: 'danger', summary: 'The .env file is too large.' });
      expect(store.pulling()).toBe(false);
    });
  });

  describe('the values', () => {
    it('shows a version’s content once the password is accepted, and hides it', async () => {
      await openWith(pageOf([VERSION, OLDER]));

      await reveal(VERSION);
      expect(store.content()).toBe(CONTENT);

      store.hide();
      expect(store.content()).toBeNull();
    });

    it('says a wrong password, and shows nothing', async () => {
      await openWith(pageOf([VERSION]));

      const revealing = store.reveal(VERSION, 'wrong');
      refuse(http.expectOne(`/api/envfiles/${VERSION.id}/reveal/`), 'invalid_password', 400);

      await expect(revealing).resolves.toBe(false);
      expect(store.revealError()?.code).toBe('invalid_password');
      expect(store.content()).toBeNull();
    });

    it('drops the content when another version is selected', async () => {
      await openWith(pageOf([VERSION, OLDER]));
      await reveal(VERSION);

      store.select(OLDER);
      expect(store.content()).toBeNull();

      store.select(VERSION);
      expect(store.content()).toBeNull();
    });

    it('drops the content when the list moves to another page', async () => {
      await openWith(pageOf([VERSION, OLDER], 30));
      await reveal(VERSION);

      store.goToPage(1, 20);
      expect(store.content()).toBeNull();
      TestBed.tick();
      listRequest().flush(pageOf([OLDEST], 30));
      await settle();
    });

    it('drops the content when the page closes', async () => {
      await openWith(pageOf([VERSION]));
      await reveal(VERSION);

      store.close();

      expect(store.content()).toBeNull();
    });

    it('drops content that arrives after the reader has moved on', async () => {
      await openWith(pageOf([VERSION, OLDER]));

      const revealing = store.reveal(VERSION, 'hunter2');
      store.select(OLDER);
      http.expectOne(`/api/envfiles/${VERSION.id}/reveal/`).flush({ content: CONTENT });
      await revealing;

      expect(store.content()).toBeNull();
      store.select(VERSION);
      expect(store.content()).toBeNull();
    });
  });

  describe('compare', () => {
    it('compares the selected version with the next row, older to newer', async () => {
      await openWith(pageOf([VERSION, OLDER, OLDEST]));

      const comparing = store.compare();
      expect(store.comparing()).toBe(true);
      (await vi.waitFor(() => http.expectOne(`/api/envfiles/${OLDER.id}/compare/?to=${VERSION.id}`))).flush(COMPARISON);
      await comparing;

      expect(store.comparing()).toBe(false);
      expect(store.comparison()).toEqual(COMPARISON);

      store.select(OLDER);
      expect(store.comparison()).toBeNull();
    });

    it('reads the version before the last row of a page on its own', async () => {
      await openWith(pageOf([VERSION, OLDER], 3));
      store.select(OLDER);

      const comparing = store.compare();
      const previous = await vi.waitFor(() =>
        http.expectOne((request) => request.url === '/api/envfiles/' && request.params.get('page_size') === '1'),
      );
      expect(previous.request.params.get('page')).toBe('3');
      previous.flush(pageOf([OLDEST], 3));
      const comparison = { ...COMPARISON, from: OLDEST.id, to: OLDER.id };
      (await vi.waitFor(() => http.expectOne(`/api/envfiles/${OLDEST.id}/compare/?to=${OLDER.id}`))).flush(comparison);
      await comparing;

      expect(store.comparison()).toEqual(comparison);
    });

    it('says why a comparison failed, beside that version only', async () => {
      await openWith(pageOf([VERSION, OLDER, OLDEST]));

      const comparing = store.compare();
      refuse(await vi.waitFor(() => http.expectOne(`/api/envfiles/${OLDER.id}/compare/?to=${VERSION.id}`)), 'not_found', 404);
      await comparing;

      expect(store.compareError()?.code).toBe('not_found');
      store.select(OLDER);
      expect(store.compareError()).toBeNull();
    });
  });

  describe('push', () => {
    it('pushes a version, says so, and selects what the server now holds', async () => {
      await openWith(pageOf([VERSION, OLDER]));
      store.select(OLDER);
      const pushed: EnvVersion = { ...OLDER, id: '7a1e4c20-5555-4d3b-8c9f-1e2d3c4b0005', source: 'pushed' };

      const pushing = store.push(OLDER, 'hunter2');
      const request = http.expectOne(`/api/envfiles/${OLDER.id}/push/`);
      expect(request.request.body).toEqual({ password: 'hunter2' });
      request.flush({ version: pushed });

      await expect(pushing).resolves.toBe(true);
      expect(lastToast()).toEqual({ severity: 'success', summary: 'Version pushed to the server.' });
      await answerReload(pageOf([pushed, PULLED, VERSION, OLDER]));
      expect(store.selected()).toEqual(pushed);
    });

    it('keeps the error for the prompt when the push is refused', async () => {
      await openWith(pageOf([VERSION]));

      const pushing = store.push(VERSION, 'wrong');
      refuse(http.expectOne(`/api/envfiles/${VERSION.id}/push/`), 'invalid_password', 400);

      await expect(pushing).resolves.toBe(false);
      expect(store.pushError()?.code).toBe('invalid_password');
      expect(toasts).not.toHaveBeenCalled();
    });

    it('goes back to the first page to show the pushed version', async () => {
      await openWith(pageOf([VERSION, OLDER], 30));
      store.goToPage(1, 20);
      TestBed.tick();
      listRequest().flush(pageOf([OLDEST], 30));
      await settle();
      store.versions();
      const pushed: EnvVersion = { ...OLDEST, id: '7a1e4c20-5555-4d3b-8c9f-1e2d3c4b0006', source: 'pushed' };

      const pushing = store.push(OLDEST, 'hunter2');
      http.expectOne(`/api/envfiles/${OLDEST.id}/push/`).flush({ version: pushed });
      await pushing;

      expect(store.page()).toBe(0);
      const request = await answerReload(pageOf([pushed, VERSION], 31));
      expect(request.request.params.get('page')).toBe('1');
      expect(store.selected()).toEqual(pushed);
    });
  });
});
