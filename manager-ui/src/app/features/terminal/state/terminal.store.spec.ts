import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, type TestRequest } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import type { Subscription } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthStore } from '@core/auth/state/auth.store';
import { MASTER } from '@core/auth/testing/identity.fixtures';
import { errorInterceptor } from '@core/http/error.interceptor';
import type { Terminal } from '../data/terminals.types';
import {
  APPLICATION,
  APPLICATION_ID,
  APPLICATION_TERMINAL,
  SERVER,
  SERVER_ID,
  TERMINAL,
  outputOf,
} from '../testing/terminal.fixtures';
import {
  TERMINAL_INPUT_BATCH_MS,
  TERMINAL_QUIET_POLL_MS,
  TERMINAL_RESIZE_DEBOUNCE_MS,
  TERMINAL_RETRY_MS,
  TerminalStore,
} from './terminal.store';
import type { TerminalFeed, TerminalPlace } from './terminal.store.types';

const AT_SERVER: TerminalPlace = { mode: 'server', id: SERVER_ID };
const IN_APPLICATION: TerminalPlace = { mode: 'application', id: APPLICATION_ID };

describe('TerminalStore', () => {
  let store: TerminalStore;
  let http: HttpTestingController;
  let feed: TerminalFeed[];
  let subscription: Subscription;

  const settle = async (): Promise<void> => {
    await vi.advanceTimersByTimeAsync(0);
  };

  const listRequest = (): TestRequest =>
    http.expectOne((request) => request.url === '/api/terminals/' && request.method === 'GET');
  const openRequest = (): TestRequest =>
    http.expectOne((request) => request.url === '/api/terminals/' && request.method === 'POST');
  const outputRequest = (cursor: number, id = TERMINAL.id): TestRequest =>
    http.expectOne(`/api/terminals/${id}/output/?cursor=${cursor}`);
  const inputRequest = (): TestRequest => http.expectOne(`/api/terminals/${TERMINAL.id}/input/`);
  const resizeRequest = (): TestRequest => http.expectOne(`/api/terminals/${TERMINAL.id}/resize/`);
  const closeRequest = (id = TERMINAL.id): TestRequest =>
    http.expectOne((request) => request.url === `/api/terminals/${id}/` && request.method === 'DELETE');

  const relist = (): void => {
    TestBed.tick();
    listRequest().flush({ results: [] });
  };

  const unreachable = (request: TestRequest): void =>
    request.error(new ProgressEvent('error'), { status: 0, statusText: '' });

  const enter = async (place: TerminalPlace = AT_SERVER, open: readonly Terminal[] = []): Promise<void> => {
    store.enter(place);
    TestBed.tick();
    if (place.mode === 'server') {
      http.expectOne(`/api/servers/${place.id}/`).flush(SERVER);
    } else {
      http.expectOne(`/api/applications/${place.id}/`).flush(APPLICATION);
    }
    listRequest().flush({ results: open });
    await settle();
  };

  const open = async (): Promise<boolean> => {
    const opening = store.open('hunter2');
    openRequest().flush(TERMINAL, { status: 201, statusText: 'Created' });
    return opening;
  };

  const text = (): string =>
    feed
      .map((item) => (item.kind === 'data' ? new TextDecoder().decode(item.bytes) : '|'))
      .join('');

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-18T12:00:00Z'));
    TestBed.configureTestingModule({
      providers: [
        TerminalStore,
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    store = TestBed.inject(TerminalStore);
    http = TestBed.inject(HttpTestingController);
    feed = [];
    subscription = store.output.subscribe((item) => feed.push(item));
  });

  afterEach(() => {
    store.leave();
    subscription.unsubscribe();
    http.verify({ ignoreCancelled: true });
    TestBed.resetTestingModule();
    vi.useRealTimers();
  });

  it('loads nothing until the page enters a place', () => {
    TestBed.tick();

    http.expectNone(() => true);
    expect(store.where()).toBeNull();
    expect(store.reattachable()).toEqual([]);
  });

  it('describes a server and offers only the terminals still open there', async () => {
    const closed: Terminal = { ...TERMINAL, id: 'closed-one', closed: true };
    await enter(AT_SERVER, [TERMINAL, APPLICATION_TERMINAL, closed]);

    expect(store.where()).toEqual({ kind: 'server', name: 'web-1', username: 'deploy' });
    expect(store.reattachable()).toEqual([TERMINAL]);
  });

  it('describes where an application runs: a Compose service, or a folder on the host', async () => {
    await enter(IN_APPLICATION, [TERMINAL, APPLICATION_TERMINAL]);

    expect(store.where()).toEqual({ kind: 'compose', name: 'shop', service: 'web' });
    expect(store.reattachable()).toEqual([APPLICATION_TERMINAL]);

    store.leave();
    store.enter({ mode: 'application', id: 'other' });
    TestBed.tick();
    http.expectOne('/api/applications/other/').flush({ ...APPLICATION, id: 'other', kind: 'host' });
    listRequest().flush({ results: [] });
    await settle();

    expect(store.where()).toEqual({ kind: 'host', name: 'shop', folder: '/srv/shop' });
  });

  it('opens with the password and the size the view last gave, then reads the output', async () => {
    await enter();
    store.resize({ cols: 100.6, rows: 30 });

    const opening = store.open('hunter2');
    expect(store.opening()).toBe(true);
    const request = openRequest();
    expect(request.request.body).toEqual({ mode: 'server', server: SERVER_ID, password: 'hunter2', cols: 100, rows: 30 });
    request.flush(TERMINAL, { status: 201, statusText: 'Created' });

    await expect(opening).resolves.toBe(true);
    expect(store.opening()).toBe(false);
    expect(store.session()).toEqual(TERMINAL);
    expect(store.attached()).toBe(true);
    expect(feed).toEqual([{ kind: 'reset' }]);
    expect(outputRequest(0).request.method).toBe('GET');
  });

  it('opens a terminal in an application by its id', async () => {
    await enter(IN_APPLICATION);

    void store.open('hunter2');

    const request = openRequest();
    expect(request.request.body).toMatchObject({ mode: 'application', application: APPLICATION_ID });
    expect(request.request.body).not.toHaveProperty('server');
    request.flush({ ...APPLICATION_TERMINAL, id: TERMINAL.id }, { status: 201, statusText: 'Created' });
    await settle();
    outputRequest(0).flush(outputOf('', 0, { closed: true, reason: 'exited', exit_status: 0 }));
    relist();
  });

  it('writes the output as it comes and reads on from its cursor, waiting a beat after a quiet answer', async () => {
    await enter();
    await open();

    outputRequest(0).flush(outputOf('$ ', 2));
    expect(text()).toBe('|$ ');
    outputRequest(2).flush(outputOf('', 2));

    await vi.advanceTimersByTimeAsync(TERMINAL_QUIET_POLL_MS - 1);
    http.expectNone(`/api/terminals/${TERMINAL.id}/output/?cursor=2`);
    await vi.advanceTimersByTimeAsync(1);
    outputRequest(2).flush(outputOf('مرحبا', 12));

    expect(text()).toBe('|$ مرحبا');
    expect(outputRequest(12).cancelled).toBe(false);
  });

  it('says when output was left out', async () => {
    await enter();
    await open();

    expect(store.skipped()).toBe(false);
    outputRequest(0).flush(outputOf('tail', 900, { skipped: true }));

    expect(store.skipped()).toBe(true);
    expect(outputRequest(900).cancelled).toBe(false);
  });

  it('ends when the shell exits, says how, and looks again for the terminals still open', async () => {
    await enter();
    await open();

    outputRequest(0).flush(outputOf('logout\r\n', 8, { closed: true, reason: 'exited', exit_status: 0 }));

    expect(text()).toBe('|logout\r\n');
    expect(store.ended()).toEqual({ reason: 'exited', exitStatus: 0, error: null });
    expect(store.attached()).toBe(false);
    relist();
    await vi.advanceTimersByTimeAsync(TERMINAL_QUIET_POLL_MS * 4);
    http.expectNone((request) => request.url.includes('/output/'));
  });

  it('keeps the password prompt open on a wrong password', async () => {
    await enter();

    const opening = store.open('wrong');
    openRequest().flush(
      { error: { code: 'invalid_password', message: 'That password is not right.' } },
      { status: 400, statusText: 'Bad Request' },
    );

    await expect(opening).resolves.toBe(false);
    expect(store.passwordError()?.code).toBe('invalid_password');
    expect(store.error()).toBeNull();
    expect(store.attached()).toBe(false);
  });

  it('closes the prompt and says why when the terminal cannot open', async () => {
    await enter();

    const opening = store.open('hunter2');
    openRequest().flush(
      { error: { code: 'too_many_terminals', message: 'Close a terminal before opening another one.' } },
      { status: 429, statusText: 'Too Many Requests' },
    );

    await expect(opening).resolves.toBe(true);
    expect(store.error()?.code).toBe('too_many_terminals');
    expect(store.passwordError()).toBeNull();
    expect(store.attached()).toBe(false);
  });

  it('batches keystrokes into one post, resends a failed post with its seq, and moves the seq on', async () => {
    await enter();
    await open();
    const startedAt = Date.now();

    store.type('l');
    store.type('s');
    await vi.advanceTimersByTimeAsync(TERMINAL_INPUT_BATCH_MS - 1);
    http.expectNone(`/api/terminals/${TERMINAL.id}/input/`);
    await vi.advanceTimersByTimeAsync(1);

    const first = inputRequest();
    const sent = first.request.body as { seq: number; data: string };
    expect(sent.data).toBe('ls');
    expect(sent.seq).toBeGreaterThanOrEqual(startedAt);
    unreachable(first);

    await vi.advanceTimersByTimeAsync(TERMINAL_RETRY_MS);
    const again = inputRequest();
    expect(again.request.body).toEqual(sent);
    again.flush({ accepted: true });

    store.type('\r');
    await vi.advanceTimersByTimeAsync(TERMINAL_INPUT_BATCH_MS);
    const next = inputRequest();
    expect((next.request.body as { seq: number }).seq).toBeGreaterThan(sent.seq);
    expect((next.request.body as { data: string }).data).toBe('\r');
    next.flush({ accepted: true });
  });

  it('sends at most 64 KiB of keystrokes in a post, never splitting a character', async () => {
    await enter();
    await open();

    store.type('é'.repeat(40000));
    await vi.advanceTimersByTimeAsync(TERMINAL_INPUT_BATCH_MS);

    const first = inputRequest();
    expect((first.request.body as { data: string }).data).toBe('é'.repeat(32768));
    first.flush({ accepted: true });
    const second = inputRequest();
    expect((second.request.body as { data: string }).data).toBe('é'.repeat(7232));
    expect((second.request.body as { seq: number }).seq).toBeGreaterThan((first.request.body as { seq: number }).seq);
    second.flush({ accepted: true });
  });

  it('resizes once the size settles, within the bounds the backend takes, and not to the size it has', async () => {
    await enter();
    await open();

    store.resize({ cols: 90, rows: 30 });
    store.resize({ cols: 1000, rows: 2 });
    await vi.advanceTimersByTimeAsync(TERMINAL_RESIZE_DEBOUNCE_MS - 1);
    http.expectNone(`/api/terminals/${TERMINAL.id}/resize/`);
    await vi.advanceTimersByTimeAsync(1);

    const request = resizeRequest();
    expect(request.request.body).toEqual({ cols: 500, rows: 5 });
    request.flush({ ...TERMINAL, cols: 500, rows: 5 });
    expect(store.session()).toMatchObject({ cols: 500, rows: 5 });

    store.resize({ cols: 500, rows: 5 });
    await vi.advanceTimersByTimeAsync(TERMINAL_RESIZE_DEBOUNCE_MS);
    http.expectNone(`/api/terminals/${TERMINAL.id}/resize/`);
  });

  it('closes the terminal for the Close button and stops reading it', async () => {
    await enter();
    await open();
    const reading = outputRequest(0);

    store.close();
    expect(store.closing()).toBe(true);
    closeRequest().flush(null, { status: 204, statusText: 'No Content' });

    expect(store.closing()).toBe(false);
    expect(store.ended()).toEqual({ reason: 'closed', exitStatus: null, error: null });
    expect(store.attached()).toBe(false);
    expect(reading.cancelled).toBe(true);
    relist();
  });

  it('closes the terminal when the page leaves while signed in', async () => {
    const restoring = TestBed.inject(AuthStore).restore();
    http.expectOne('/api/auth/me/').flush(MASTER);
    await restoring;
    await enter();
    await open();
    const reading = outputRequest(0);

    store.leave();

    closeRequest().flush(null, { status: 204, statusText: 'No Content' });
    expect(reading.cancelled).toBe(true);
    expect(store.place()).toBeNull();
    expect(store.attached()).toBe(false);
  });

  it('leaves without a request once signed out, since signing out closed it already', async () => {
    await enter();
    await open();
    const reading = outputRequest(0);

    store.leave();

    http.expectNone((request) => request.method === 'DELETE');
    expect(reading.cancelled).toBe(true);
  });

  it('reattaches without a password, from what the backend kept, and fits it to the view', async () => {
    await enter(AT_SERVER, [TERMINAL]);
    store.resize({ cols: 100, rows: 30 });

    store.reattach(TERMINAL);

    http.expectNone((request) => request.method === 'POST' && request.url === '/api/terminals/');
    expect(store.attached()).toBe(true);
    expect(store.reattached()).toBe(true);
    expect(store.reattachable()).toEqual([]);
    outputRequest(0).flush(outputOf('deploy@web-1:~$ ', 640, { skipped: true }));
    expect(store.skipped()).toBe(false);
    expect(text()).toBe('|deploy@web-1:~$ ');

    await vi.advanceTimersByTimeAsync(TERMINAL_RESIZE_DEBOUNCE_MS);
    const request = resizeRequest();
    expect(request.request.body).toEqual({ cols: 100, rows: 30 });
    request.flush({ ...TERMINAL, cols: 100, rows: 30 });
    expect(outputRequest(640).cancelled).toBe(false);
  });

  it('reads again from the same cursor when the manager could not be reached', async () => {
    await enter();
    await open();

    unreachable(outputRequest(0));
    await vi.advanceTimersByTimeAsync(TERMINAL_RETRY_MS - 1);
    http.expectNone(`/api/terminals/${TERMINAL.id}/output/?cursor=0`);
    await vi.advanceTimersByTimeAsync(1);
    outputRequest(0).flush(outputOf('ok', 2));

    expect(text()).toBe('|ok');
    expect(store.ended()).toBeNull();
    expect(outputRequest(2).cancelled).toBe(false);
  });

  it('ends with the reason the backend gives once the terminal is gone', async () => {
    await enter();
    await open();

    outputRequest(0).flush(
      { error: { code: 'terminal_not_found', message: 'There is no such terminal open for you.' } },
      { status: 404, statusText: 'Not Found' },
    );

    expect(store.ended()?.error?.code).toBe('terminal_not_found');
    expect(store.attached()).toBe(false);
    relist();
  });

  it('closes a terminal it offered to reattach, and looks again', async () => {
    await enter(AT_SERVER, [TERMINAL]);

    store.discard(TERMINAL);
    expect(store.discarding()).toBe(TERMINAL.id);
    closeRequest().flush(null, { status: 204, statusText: 'No Content' });

    expect(store.discarding()).toBeNull();
    relist();
    await settle();
    expect(store.reattachable()).toEqual([]);
  });

  it('closes a terminal that opened after the page had left', async () => {
    const restoring = TestBed.inject(AuthStore).restore();
    http.expectOne('/api/auth/me/').flush(MASTER);
    await restoring;
    await enter();

    const opening = store.open('hunter2');
    store.leave();
    openRequest().flush(TERMINAL, { status: 201, statusText: 'Created' });

    await expect(opening).resolves.toBe(true);
    closeRequest().flush(null, { status: 204, statusText: 'No Content' });
    expect(store.attached()).toBe(false);
    http.expectNone((request) => request.url.includes('/output/'));
  });
});
