import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, type TestRequest } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import type { ServerSummary } from '../data/servers.types';
import { HOST_KEY_CONFIRMATION, SERVER, SUMMARY, pageOf } from '../testing/servers.fixtures';
import { ServersStore } from './servers.store';

const DETAIL = `/api/servers/${SERVER.id}/`;

describe('ServersStore', () => {
  let store: ServersStore;
  let http: HttpTestingController;

  const listRequest = (): TestRequest => http.expectOne((request) => request.url === '/api/servers/');
  const hostKeysRequest = (): TestRequest =>
    http.expectOne((request) => request.url === '/api/servers/host-keys/');

  const openList = (): void => {
    store.openList();
    TestBed.tick();
    hostKeysRequest().flush(pageOf([]));
  };

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
      openList();
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
      openList();
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
      openList();
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
      openList();
      listRequest().flush(pageOf([SUMMARY]));
      await settle();
      expect(store.servers()).toEqual([SUMMARY]);

      store.closeList();
      TestBed.tick();

      expect(store.servers()).toEqual([]);
    });
  });

  describe('host keys awaiting confirmation', () => {
    const showPending = async (): Promise<void> => {
      store.openList();
      TestBed.tick();
      hostKeysRequest().flush(pageOf([HOST_KEY_CONFIRMATION]));
      listRequest().flush(pageOf([SUMMARY]));
      await settle();
    };

    it('loads them with the list', async () => {
      await showPending();

      expect(store.pendingHostKeys()).toEqual([HOST_KEY_CONFIRMATION]);
    });

    it('confirms one, busy while it does, then reads them again', async () => {
      await showPending();

      const deciding = store.decideHostKey(HOST_KEY_CONFIRMATION, 'confirm');
      expect(store.decidingHostKeys().has(HOST_KEY_CONFIRMATION.id)).toBe(true);
      http
        .expectOne(`/api/servers/host-keys/${HOST_KEY_CONFIRMATION.id}/confirm/`)
        .flush({ ...HOST_KEY_CONFIRMATION, status: 'confirmed' });

      await expect(deciding).resolves.toBe(true);
      expect(store.decidingHostKeys().size).toBe(0);
      TestBed.tick();
      hostKeysRequest().flush(pageOf([]));
      await settle();
      expect(store.pendingHostKeys()).toEqual([]);
    });

    it('keeps why a decision failed, and reads them again', async () => {
      await showPending();

      const deciding = store.decideHostKey(HOST_KEY_CONFIRMATION, 'reject');
      http
        .expectOne(`/api/servers/host-keys/${HOST_KEY_CONFIRMATION.id}/reject/`)
        .flush(
          { error: { code: 'host_key_confirmation_missing', message: 'Server prose' } },
          { status: 404, statusText: 'Not Found' },
        );

      await expect(deciding).resolves.toBe(false);
      expect(store.hostKeyDecisionError()?.code).toBe('host_key_confirmation_missing');
      TestBed.tick();
      hostKeysRequest().flush(pageOf([]));
      await settle();
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

  describe('the public key', () => {
    it('reads the key the manager signs in with, and forgets it on hide', async () => {
      await showServer();

      const reading = store.readPublicKey();
      expect(store.readingKey()).toBe(true);
      http.expectOne(`${DETAIL}public-key/`).flush({ public_key: 'ssh-ed25519 AAAA dbs' });

      await expect(reading).resolves.toBe(true);
      expect(store.publicKey()).toBe('ssh-ed25519 AAAA dbs');

      store.hidePublicKey();
      expect(store.publicKey()).toBeNull();
    });

    it('keeps why a password server has no key', async () => {
      await showServer();

      const reading = store.readPublicKey();
      http
        .expectOne(`${DETAIL}public-key/`)
        .flush({ error: { code: 'no_private_key', message: 'Server prose' } }, { status: 400, statusText: 'Bad Request' });

      await expect(reading).resolves.toBe(false);
      expect(store.keyError()?.code).toBe('no_private_key');
      expect(store.publicKey()).toBeNull();
    });
  });

  describe('another record of the same machine', () => {
    const twinsOf = async (others: readonly ServerSummary[]): Promise<void> => {
      store.watchTwins(true);
      store.select(SERVER.id);
      TestBed.tick();
      http.expectOne(DETAIL).flush(SERVER);
      const search = await vi.waitFor(() => {
        TestBed.tick();
        return listRequest();
      });
      expect(search.request.params.get('search')).toBe(SERVER.host);
      search.flush(pageOf(others));
    };

    it('reads each server at the same address and user, and keeps the ones with the same host key', async () => {
      const same: ServerSummary = { ...SUMMARY, id: 'same', name: 'Web again' };
      const otherKey: ServerSummary = { ...SUMMARY, id: 'other-key', name: 'Rebuilt web' };
      const otherUser: ServerSummary = { ...SUMMARY, id: 'other-user', username: 'root' };
      await twinsOf([SUMMARY, same, otherKey, otherUser]);

      (await vi.waitFor(() => http.expectOne('/api/servers/same/'))).flush({ ...SERVER, id: 'same', name: 'Web again' });
      http.expectOne('/api/servers/other-key/').flush({ ...SERVER, id: 'other-key', host_key: 'web-1 ssh-ed25519 BBBB' });
      await settle();

      expect(store.twins().map((twin) => twin.id)).toEqual(['same']);
    });

    it('reads no server when none shares the address', async () => {
      await twinsOf([SUMMARY, { ...SUMMARY, id: 'elsewhere', host: 'web-10.example.com' }]);
      await settle();

      expect(store.twins()).toEqual([]);
    });

    it('merges into the other record with the password', async () => {
      await twinsOf([]);
      await settle();

      const merging = store.merge('same', 'hunter2');
      expect(store.merging()).toBe(true);
      const request = http.expectOne(`${DETAIL}merge/`);
      expect(request.request.body).toEqual({ into: 'same', account_password: 'hunter2' });
      request.flush({ ...SERVER, id: 'same' });

      await expect(merging).resolves.toBe(true);
      expect(store.merging()).toBe(false);
    });

    it('keeps why a merge was refused', async () => {
      await twinsOf([]);
      await settle();

      const merging = store.merge('same', 'hunter2');
      http
        .expectOne(`${DETAIL}merge/`)
        .flush({ error: { code: 'servers_differ', message: 'Server prose' } }, { status: 400, statusText: 'Bad Request' });

      await expect(merging).resolves.toBe(false);
      expect(store.mergeError()?.code).toBe('servers_differ');
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
    it('deletes the server on screen with the password', async () => {
      await showServer();

      const removing = store.remove('hunter2');
      expect(store.deleting()).toBe(true);
      const request = http.expectOne(DETAIL);
      expect(request.request.method).toBe('DELETE');
      expect(request.request.body).toEqual({ account_password: 'hunter2' });
      request.flush(null, { status: 204, statusText: 'No Content' });

      await expect(removing).resolves.toBe(true);
      expect(store.deleting()).toBe(false);
    });

    it('keeps a wrong password for the prompt', async () => {
      await showServer();

      const removing = store.remove('wrong');
      http
        .expectOne(DETAIL)
        .flush({ error: { code: 'invalid_password', message: 'Server prose' } }, { status: 400, statusText: 'Bad Request' });

      await expect(removing).resolves.toBe(false);
      expect(store.deleteError()?.code).toBe('invalid_password');
    });
  });
});
