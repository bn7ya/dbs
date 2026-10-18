import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, type TestRequest } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { APPLICATION, CHECKED, SERVER_ID, SUMMARY, pageOf } from '../testing/applications.fixtures';
import { ApplicationsStore } from './applications.store';

const DETAIL = `/api/applications/${APPLICATION.id}/`;

describe('ApplicationsStore', () => {
  let store: ApplicationsStore;
  let http: HttpTestingController;

  const listRequest = (): TestRequest => http.expectOne((request) => request.url === '/api/applications/');
  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const showApplication = async (): Promise<void> => {
    store.select(APPLICATION.id);
    TestBed.tick();
    http.expectOne(DETAIL).flush(APPLICATION);
    await settle();
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        ApplicationsStore,
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    store = TestBed.inject(ApplicationsStore);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
  });

  describe('the list', () => {
    it('loads nothing until a list opens', () => {
      TestBed.tick();

      http.expectNone((request) => request.url === '/api/applications/');
      expect(store.applications()).toEqual([]);
    });

    it('loads every application, or one server’s', async () => {
      store.openList(null);
      TestBed.tick();
      const every = listRequest();
      expect(every.request.params.has('server')).toBe(false);
      every.flush(pageOf([SUMMARY], 41));
      await settle();
      expect(store.applications()).toEqual([SUMMARY]);
      expect(store.count()).toBe(41);

      store.openList(SERVER_ID);
      TestBed.tick();
      const scoped = listRequest();
      expect(scoped.request.params.get('server')).toBe(SERVER_ID);
      scoped.flush(pageOf([]));
      await settle();
      expect(store.listEmpty()).toBe(true);
    });

    it('keeps the page on screen while the next one loads, and forgets it when the list closes', async () => {
      store.openList(null);
      TestBed.tick();
      listRequest().flush(pageOf([SUMMARY], 41));
      await settle();
      expect(store.applications()).toEqual([SUMMARY]);

      store.goToPage(1, 20);
      TestBed.tick();
      const next = listRequest();
      expect(next.request.params.get('page')).toBe('2');
      expect(store.applications()).toEqual([SUMMARY]);
      next.flush(pageOf([], 41));
      await settle();

      store.closeList();
      TestBed.tick();
      expect(store.applications()).toEqual([]);
    });
  });

  describe('one application', () => {
    it('treats a missing application as not found', async () => {
      store.select('gone');
      TestBed.tick();
      http
        .expectOne('/api/applications/gone/')
        .flush({ error: { code: 'not_found', message: 'Server prose' } }, { status: 404, statusText: 'Not Found' });
      await settle();

      expect(store.applicationMissing()).toBe(true);
    });

    it('shows the application as the check left it, with both django-dbs versions', async () => {
      await showApplication();

      const checking = store.check();
      expect(store.checking()).toBe(true);
      http.expectOne(`${DETAIL}check/`).flush({ ...CHECKED, last_check_status: 'problem' });

      await expect(checking).resolves.toBe(true);
      expect(store.application()?.last_check_status).toBe('problem');
      expect(store.versions()).toEqual({ local_version: '0.8.0', remote_version: '0.8.0', installed: true, compatible: true });
    });

    it('keeps why a check failed and reloads the application, which records it too', async () => {
      await showApplication();

      const checking = store.check();
      http
        .expectOne(`${DETAIL}check/`)
        .flush({ error: { code: 'ssh_unreachable', message: 'Server prose' } }, { status: 502, statusText: 'Bad Gateway' });
      await expect(checking).resolves.toBe(false);
      expect(store.checkFailure()).toBe('ssh_unreachable');

      TestBed.tick();
      http.expectOne(DETAIL).flush({ ...APPLICATION, last_check_status: 'failed', last_check_error: 'ssh_unreachable' });
      await settle();
      store.checkError.set(null);
      expect(store.checkFailure()).toBe('ssh_unreachable');
    });

    it('switches to another Python and checks again', async () => {
      await showApplication();

      const switching = store.usePython('/app/venv/bin/python', 'hunter2');
      const patch = http.expectOne(DETAIL);
      expect(patch.request.body).toEqual({ python_path: '/app/venv/bin/python', account_password: 'hunter2' });
      patch.flush({ ...APPLICATION, python_path: '/app/venv/bin/python' });
      (await vi.waitFor(() => http.expectOne(`${DETAIL}check/`))).flush(CHECKED);

      await expect(switching).resolves.toBe(true);
    });

    it('does not check again when the switch was refused', async () => {
      await showApplication();

      const switching = store.usePython('/app/venv/bin/python');
      http.expectOne(DETAIL).flush(
        { error: { code: 'invalid', message: 'Server prose', fields: { account_password: ['required'] } } },
        { status: 400, statusText: 'Bad Request' },
      );

      await expect(switching).resolves.toBe(false);
      expect(store.saveError()?.fields?.['account_password']).toEqual(['required']);
    });
  });

  describe('the backup passphrase', () => {
    it('holds the passphrase while shown, and drops it on hide or for another application', async () => {
      await showApplication();

      const revealing = store.revealPassphrase('secret');
      const request = http.expectOne(`${DETAIL}passphrase/`);
      expect(request.request.body).toEqual({ password: 'secret' });
      request.flush({ passphrase: 'correct horse battery staple' });
      await expect(revealing).resolves.toBe(true);
      expect(store.passphrase()).toBe('correct horse battery staple');

      store.hidePassphrase();
      expect(store.passphrase()).toBeNull();

      const again = store.revealPassphrase('secret');
      http.expectOne(`${DETAIL}passphrase/`).flush({ passphrase: 'correct horse battery staple' });
      await again;
      store.select('another');
      TestBed.tick();
      http.expectOne('/api/applications/another/').flush({ ...APPLICATION, id: 'another' });
      await settle();
      expect(store.passphrase()).toBeNull();
    });

    it('reads the passphrase from the application and shows it as saved', async () => {
      await showApplication();

      const capturing = store.capturePassphrase();
      http.expectOne(`${DETAIL}passphrase/capture/`).flush({ captured: true });
      await expect(capturing).resolves.toBe(true);

      TestBed.tick();
      http.expectOne(DETAIL).flush({ ...APPLICATION, has_backup_passphrase: true });
      await settle();
    });

    it('keeps why the passphrase could not be read', async () => {
      await showApplication();

      const capturing = store.capturePassphrase();
      http
        .expectOne(`${DETAIL}passphrase/capture/`)
        .flush({ error: { code: 'container_not_running', message: 'Server prose' } }, { status: 502, statusText: 'Bad Gateway' });

      await expect(capturing).resolves.toBe(false);
      expect(store.captureError()?.code).toBe('container_not_running');
    });
  });

  describe('removing an application', () => {
    it('removes the application on screen with the password, and keeps a wrong one', async () => {
      await showApplication();

      const wrong = store.remove('wrong');
      http
        .expectOne(DETAIL)
        .flush({ error: { code: 'invalid_password', message: 'Server prose' } }, { status: 400, statusText: 'Bad Request' });
      await expect(wrong).resolves.toBe(false);
      expect(store.deleteError()?.code).toBe('invalid_password');

      const removing = store.remove('hunter2');
      expect(store.deleting()).toBe(true);
      const request = http.expectOne(DETAIL);
      expect(request.request.method).toBe('DELETE');
      expect(request.request.body).toEqual({ account_password: 'hunter2' });
      request.flush(null, { status: 204, statusText: 'No Content' });
      await expect(removing).resolves.toBe(true);
    });
  });
});
