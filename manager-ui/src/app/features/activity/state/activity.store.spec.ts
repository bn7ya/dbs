import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, type TestRequest } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { ENTRY, FAILED, SERVER_ID, pageOf } from '../testing/activity.fixtures';
import { ActivityStore } from './activity.store';

describe('ActivityStore', () => {
  let store: ActivityStore;
  let http: HttpTestingController;

  const listRequest = (): TestRequest => http.expectOne((request) => request.url === '/api/activity/');

  // A resource resolves its stream on a promise, so a flushed value lands a microtask later.
  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const openWith = async (server: string | null, count = 41): Promise<void> => {
    store.open(server);
    TestBed.tick();
    listRequest().flush(pageOf([ENTRY], count));
    await settle();
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        ActivityStore,
        // The real interceptor: the store's contract is that it only ever sees an ApiError.
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    store = TestBed.inject(ActivityStore);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    // The Vitest runner does not reset between tests the way Karma did.
    TestBed.resetTestingModule();
  });

  it('loads nothing until the page opens it', () => {
    TestBed.tick();

    http.expectNone((request) => request.url === '/api/activity/');
    expect(store.entries()).toEqual([]);
    expect(store.pending()).toBe(false);
  });

  it('lists every server when opened without one', async () => {
    store.open(null);
    TestBed.tick();
    expect(store.pending()).toBe(true);

    const request = listRequest();
    expect(request.request.params.get('page')).toBe('1');
    expect(request.request.params.get('page_size')).toBe('20');
    expect(request.request.params.has('server')).toBe(false);
    expect(request.request.params.has('status')).toBe(false);
    expect(request.request.params.has('action')).toBe(false);
    request.flush(pageOf([ENTRY, FAILED], 41));
    await settle();

    expect(store.entries()).toEqual([ENTRY, FAILED]);
    expect(store.count()).toBe(41);
    expect(store.pending()).toBe(false);
    expect(store.empty()).toBe(false);
  });

  it('lists one server when opened with it', async () => {
    store.open(SERVER_ID);
    TestBed.tick();

    const request = listRequest();
    expect(request.request.params.get('server')).toBe(SERVER_ID);
    request.flush(pageOf([ENTRY]));
    await settle();

    expect(store.entries()).toEqual([ENTRY]);
  });

  it('sends a filter and starts it again at the first page', async () => {
    await openWith(null);
    store.goToPage(1, 20);
    TestBed.tick();
    expect(listRequest().request.params.get('page')).toBe('2');

    store.setStatus('failed');
    TestBed.tick();
    const filtered = listRequest();
    expect(filtered.request.params.get('status')).toBe('failed');
    expect(filtered.request.params.get('page')).toBe('1');
    expect(store.filtered()).toBe(true);
    filtered.flush(pageOf([FAILED]));
    await settle();

    store.setAction('server.check');
    TestBed.tick();
    const both = listRequest();
    expect(both.request.params.get('status')).toBe('failed');
    expect(both.request.params.get('action')).toBe('server.check');
    both.flush(pageOf([], 0));
    await settle();

    expect(store.empty()).toBe(true);
    expect(store.filtered()).toBe(true);
  });

  it('clears both filters at once', async () => {
    await openWith(null);
    store.setStatus('failed');
    store.setAction('server.check');
    TestBed.tick();
    listRequest().flush(pageOf([], 0));
    await settle();

    store.clearFilters();
    TestBed.tick();
    const request = listRequest();
    expect(request.request.params.has('status')).toBe(false);
    expect(request.request.params.has('action')).toBe(false);
    expect(store.filtered()).toBe(false);
    request.flush(pageOf([ENTRY]));
    await settle();
  });

  it('keeps the page on screen while the next one loads', async () => {
    await openWith(null);
    // Read it, as the page's template does: the page kept is the one last shown.
    expect(store.entries()).toEqual([ENTRY]);

    store.goToPage(1, 20);
    TestBed.tick();
    const next = listRequest();
    expect(store.entries()).toEqual([ENTRY]);
    expect(store.loading()).toBe(true);
    expect(store.pending()).toBe(false);

    next.flush(pageOf([FAILED], 41));
    await settle();
    expect(store.entries()).toEqual([FAILED]);
  });

  it('holds the failure as an ApiError and retries on reload', async () => {
    store.open(null);
    TestBed.tick();
    listRequest().flush(
      { error: { code: 'unknown', message: 'Server prose' } },
      { status: 500, statusText: 'Server Error' },
    );
    await settle();

    expect(store.error()?.code).toBe('unknown');

    store.reload();
    TestBed.tick();
    listRequest().flush(pageOf([ENTRY]));
    await settle();
    expect(store.error()).toBeNull();
    expect(store.entries()).toEqual([ENTRY]);
  });

  it('forgets the rows when the page closes', async () => {
    await openWith(null);

    store.close();
    TestBed.tick();

    expect(store.entries()).toEqual([]);
  });

  it('starts every visit with the filters clear and on the first page', async () => {
    await openWith(SERVER_ID);
    store.setStatus('failed');
    TestBed.tick();
    listRequest().flush(pageOf([FAILED], 41));
    await settle();
    store.goToPage(2, 20);
    TestBed.tick();
    listRequest().flush(pageOf([FAILED], 41));
    await settle();
    store.close();
    TestBed.tick();

    store.open(SERVER_ID);
    TestBed.tick();
    const request = listRequest();
    expect(request.request.params.get('page')).toBe('1');
    expect(request.request.params.has('status')).toBe(false);
    expect(store.filtered()).toBe(false);
    request.flush(pageOf([ENTRY]));
    await settle();
  });
});
