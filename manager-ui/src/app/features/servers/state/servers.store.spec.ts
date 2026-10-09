import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, type TestRequest } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { CREATE, SERVER, SUMMARY, pageOf } from '../testing/servers.fixtures';
import { ServersStore } from './servers.store';

const DETAIL = `/api/servers/${SERVER.id}/`;

describe('ServersStore', () => {
  let store: ServersStore;
  let http: HttpTestingController;

  const listRequest = (): TestRequest => http.expectOne((request) => request.url === '/api/servers/');

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const showServer = async (): Promise<void> => {
    store.select(SERVER.id);
    TestBed.tick();
    http.expectOne(DETAIL).flush(SERVER);
    await settle();
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        ServersStore,
        // The real interceptor: the store's contract is that it only ever sees an ApiError.
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    store = TestBed.inject(ServersStore);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    // The Vitest runner does not reset between tests the way Karma did.
    TestBed.resetTestingModule();
  });

  describe('the list', () => {
    it('loads nothing until the list page opens', () => {
      TestBed.tick();

      http.expectNone((request) => request.url === '/api/servers/');
      expect(store.servers()).toEqual([]);
    });

    it('loads the first page when the list opens', async () => {
      store.openList();
      TestBed.tick();
      expect(store.listPending()).toBe(true);

      const request = listRequest();
      expect(request.request.params.get('page')).toBe('1');
      expect(request.request.params.get('page_size')).toBe('20');
      request.flush(pageOf([SUMMARY], 41));
      await settle();

      expect(store.servers()).toEqual([SUMMARY]);
      expect(store.count()).toBe(41);
      expect(store.listPending()).toBe(false);
      expect(store.listEmpty()).toBe(false);
    });

    it('keeps the page on screen while the next one loads', async () => {
      store.openList();
      TestBed.tick();
      listRequest().flush(pageOf([SUMMARY], 41));
      await settle();
      expect(store.servers()).toEqual([SUMMARY]);

      store.goToPage(1, 20);
      TestBed.tick();
      const next = listRequest();
      expect(next.request.params.get('page')).toBe('2');
      expect(store.servers()).toEqual([SUMMARY]);
      expect(store.listLoading()).toBe(true);

      next.flush(pageOf([], 41));
      await settle();
      expect(store.servers()).toEqual([]);
    });

    it('holds the failure as an ApiError and retries on reload', async () => {
      store.openList();
      TestBed.tick();
      listRequest().flush(
        { error: { code: 'unknown', message: 'Server prose' } },
        { status: 500, statusText: 'Server Error' },
      );
      await settle();

      expect(store.listError()?.code).toBe('unknown');

      store.reloadList();
      TestBed.tick();
      listRequest().flush(pageOf([SUMMARY]));
      await settle();
      expect(store.listError()).toBeNull();
      expect(store.servers()).toEqual([SUMMARY]);
    });

    it('forgets the rows when the list closes, so a deleted server never flashes back', async () => {
      store.openList();
      TestBed.tick();
      listRequest().flush(pageOf([SUMMARY]));
      await settle();
      expect(store.servers()).toEqual([SUMMARY]);

      store.closeList();
      TestBed.tick();

      expect(store.servers()).toEqual([]);
    });
  });

  describe('adding a server', () => {
    it('posts the server and resolves with it as created', async () => {
      const creating = store.create(CREATE);
      expect(store.saving()).toBe(true);

      const request = http.expectOne('/api/servers/');
      expect(request.request.body).toEqual(CREATE);
      request.flush(SERVER, { status: 201, statusText: 'Created' });

      await expect(creating).resolves.toEqual(SERVER);
      expect(store.saving()).toBe(false);
      expect(store.saveError()).toBeNull();
    });

    it('keeps the field codes the backend sent', async () => {
      const creating = store.create(CREATE);
      http.expectOne('/api/servers/').flush(
        { error: { code: 'invalid', message: 'Server prose', fields: { name: ['name_taken'] } } },
        { status: 400, statusText: 'Bad Request' },
      );

      await expect(creating).resolves.toBeNull();
      expect(store.saveError()?.fields).toEqual({ name: ['name_taken'] });
    });
  });

  describe('checking a server', () => {
    it('shows the server as the check left it', async () => {
      await showServer();

      const checking = store.check();
      expect(store.checking()).toBe(true);
      http.expectOne(`${DETAIL}check/`).flush({ ...SERVER, last_check_status: 'problem' });

      await expect(checking).resolves.toBe(true);
      expect(store.checking()).toBe(false);
      expect(store.server()?.last_check_status).toBe('problem');
    });

    it('keeps the failure and reloads the server, which records it too', async () => {
      await showServer();

      const checking = store.check();
      http.expectOne(`${DETAIL}check/`).flush(
        { error: { code: 'ssh_unreachable', message: 'Server prose' } },
        { status: 502, statusText: 'Bad Gateway' },
      );

      await expect(checking).resolves.toBe(false);
      expect(store.checkError()?.code).toBe('ssh_unreachable');
      expect(store.checkFailure()).toBe('ssh_unreachable');

      TestBed.tick();
      http
        .expectOne(DETAIL)
        .flush({ ...SERVER, last_check_status: 'failed', last_check_error: 'ssh_unreachable' });
      await settle();
      expect(store.server()?.last_check_status).toBe('failed');
    });

    it('reads a changed host key as blocking, from a fresh check or from the row', async () => {
      await showServer();

      const checking = store.check();
      http.expectOne(`${DETAIL}check/`).flush(
        { error: { code: 'host_key_changed', message: 'Server prose' } },
        { status: 409, statusText: 'Conflict' },
      );
      await checking;
      expect(store.hostKeyChanged()).toBe(true);

      TestBed.tick();
      http
        .expectOne(DETAIL)
        .flush({ ...SERVER, last_check_status: 'failed', last_check_error: 'host_key_changed' });
      await settle();
      store.checkError.set(null);
      expect(store.hostKeyChanged()).toBe(true);

      store.select(undefined);
      TestBed.tick();
      await showServer();
      expect(store.hostKeyChanged()).toBe(false);
    });

    it('treats a missing server as not found', async () => {
      store.select('gone');
      TestBed.tick();
      http
        .expectOne('/api/servers/gone/')
        .flush({ error: { code: 'not_found', message: 'Server prose' } }, { status: 404, statusText: 'Not Found' });
      await settle();

      expect(store.serverMissing()).toBe(true);
      expect(store.server()).toBeUndefined();
    });
  });

  describe('the backup passphrase', () => {
    it('holds the passphrase while shown and drops it on hide', async () => {
      await showServer();

      const revealing = store.revealPassphrase('secret');
      const request = http.expectOne(`${DETAIL}passphrase/`);
      expect(request.request.body).toEqual({ password: 'secret' });
      request.flush({ passphrase: 'correct horse battery staple' });

      await expect(revealing).resolves.toBe(true);
      expect(store.passphrase()).toBe('correct horse battery staple');

      store.hidePassphrase();
      expect(store.passphrase()).toBeNull();
    });

    it('drops it when another server is shown', async () => {
      await showServer();
      const revealing = store.revealPassphrase('secret');
      http.expectOne(`${DETAIL}passphrase/`).flush({ passphrase: 'correct horse battery staple' });
      await revealing;

      store.select('another');
      TestBed.tick();
      http.expectOne('/api/servers/another/').flush({ ...SERVER, id: 'another' });
      await settle();

      expect(store.passphrase()).toBeNull();
    });

    it('keeps a wrong password as an error and shows nothing', async () => {
      await showServer();

      const revealing = store.revealPassphrase('wrong');
      http.expectOne(`${DETAIL}passphrase/`).flush(
        { error: { code: 'invalid_password', message: 'Server prose' } },
        { status: 400, statusText: 'Bad Request' },
      );

      await expect(revealing).resolves.toBe(false);
      expect(store.revealError()?.code).toBe('invalid_password');
      expect(store.passphrase()).toBeNull();
    });
  });

  describe('the host key', () => {
    it('re-pins behind the password and shows the server as saved', async () => {
      await showServer();

      const pinning = store.repinHostKey('web-1 ssh-ed25519 BBBB', 'secret');
      const request = http.expectOne(`${DETAIL}host-key/`);
      expect(request.request.body).toEqual({ host_key: 'web-1 ssh-ed25519 BBBB', password: 'secret' });
      request.flush({ ...SERVER, host_key_fingerprint: 'SHA256:new' });

      await expect(pinning).resolves.toBe(true);
      expect(store.server()?.host_key_fingerprint).toBe('SHA256:new');
    });
  });

  describe('deleting a server', () => {
    it('deletes the server on screen', async () => {
      await showServer();

      const removing = store.remove();
      expect(store.deleting()).toBe(true);
      const request = http.expectOne(DETAIL);
      expect(request.request.method).toBe('DELETE');
      request.flush(null, { status: 204, statusText: 'No Content' });

      await expect(removing).resolves.toBe(true);
      expect(store.deleting()).toBe(false);
    });
  });
});
