import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, type TestRequest } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthStore } from '@core/auth/state/auth.store';
import { MASTER } from '@core/auth/testing/identity.fixtures';
import { errorInterceptor } from '@core/http/error.interceptor';
import { JOB_POLL_MS } from '@core/jobs/job-watcher';
import {
  ACTIVITY_ID,
  FAILED_JOB,
  LISTED,
  NEEDS_PASSWORD,
  REFUSED_ROLE,
  RUNNING_JOB,
  STARTED,
  WRONG_PASSWORD,
} from '../testing/console.fixtures';
import { CONSOLE_HISTORY_MAX, ConsoleStore } from './console.store';

const ACTIVITY_URL = `/api/activity/${ACTIVITY_ID}/`;

describe('ConsoleStore', () => {
  let store: ConsoleStore;
  let http: HttpTestingController;

  const consoleRequest = (): TestRequest => http.expectOne('/api/console/');

  const signIn = async (): Promise<void> => {
    const restoring = TestBed.inject(AuthStore).restore();
    http.expectOne('/api/auth/me/').flush(MASTER);
    await restoring;
    TestBed.tick();
  };

  beforeEach(() => {
    vi.useFakeTimers();
    TestBed.configureTestingModule({
      providers: [
        ConsoleStore,
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    store = TestBed.inject(ConsoleStore);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    try {
      http.verify();
    } finally {
      TestBed.resetTestingModule();
      vi.useRealTimers();
    }
  });

  it('runs a line and keeps it with its output and exit code', async () => {
    await signIn();

    const running = store.run('  server list ');
    expect(store.busy()).toBe(true);
    expect(store.entries()).toMatchObject([{ line: 'server list', state: 'running' }]);
    const request = consoleRequest();
    expect(request.request.body).toEqual({ line: 'server list' });
    request.flush(LISTED);

    await expect(running).resolves.toMatchObject({ state: 'done', exitCode: 0, output: LISTED.output });
    expect(store.busy()).toBe(false);
    expect(store.entries()).toHaveLength(1);
    expect(store.history()).toEqual(['server list']);
  });

  it('runs nothing for a blank line', async () => {
    await expect(store.run('   ')).resolves.toBeNull();

    http.expectNone('/api/console/');
    expect(store.entries()).toEqual([]);
  });

  it('keeps a failed command with its exit code and the code of its error', async () => {
    const running = store.run('server delete web-1');
    consoleRequest().flush(REFUSED_ROLE);

    await expect(running).resolves.toMatchObject({ state: 'done', exitCode: 1, errorCode: 'role_required' });
  });

  it('keeps a line the backend refused with the code it gave the line', async () => {
    const running = store.run('server list "web');
    consoleRequest().flush(
      { error: { code: 'invalid', message: 'Close every quote in the command.', fields: { line: ['unbalanced_quotes'] } } },
      { status: 400, statusText: 'Bad Request' },
    );

    const entry = await running;
    expect(entry?.state).toBe('refused');
    expect(entry?.error?.code).toBe('unbalanced_quotes');
  });

  it('says when the previous command is still running', async () => {
    const running = store.run('server list');
    consoleRequest().flush(
      { error: { code: 'console_busy', message: 'Your previous command is still running.' } },
      { status: 429, statusText: 'Too Many Requests' },
    );

    await expect(running).resolves.toMatchObject({ state: 'refused', error: { code: 'console_busy' } });
  });

  it('runs one command at a time', async () => {
    void store.run('server list');

    await expect(store.run('app list')).resolves.toBeNull();
    consoleRequest().flush(LISTED);
  });

  it('runs the same line again with the password when it asks for one', async () => {
    const running = store.run('backup delete 7');
    consoleRequest().flush(NEEDS_PASSWORD);
    const entry = await running;
    expect(entry?.state).toBe('password');

    const answering = store.runWithPassword(entry!, 'hunter2');
    const request = consoleRequest();
    expect(request.request.body).toEqual({ line: 'backup delete 7', password: 'hunter2' });
    request.flush({ ...LISTED, output: 'Deleted.\n' });

    await expect(answering).resolves.toBe(true);
    expect(store.entries()).toMatchObject([{ id: entry!.id, state: 'done', exitCode: 0, output: 'Deleted.\n' }]);
  });

  it('keeps the prompt open on a wrong password and leaves the command unrun', async () => {
    const running = store.run('backup delete 7');
    consoleRequest().flush(NEEDS_PASSWORD);
    const entry = (await running)!;

    const answering = store.runWithPassword(entry, 'wrong');
    consoleRequest().flush(WRONG_PASSWORD);

    await expect(answering).resolves.toBe(false);
    expect(store.passwordError()?.code).toBe('invalid_password');
    expect(store.entries()).toMatchObject([{ state: 'password' }]);
  });

  it('follows each job a command started until it ends', async () => {
    const running = store.run('backup take shop');
    consoleRequest().flush(STARTED);
    await running;

    expect(store.jobs().get(ACTIVITY_ID)).toEqual({ id: ACTIVITY_ID, job: null, error: null });
    await vi.advanceTimersByTimeAsync(0);
    http.expectOne(ACTIVITY_URL).flush(RUNNING_JOB);
    expect(store.jobs().get(ACTIVITY_ID)?.job?.status).toBe('running');

    await vi.advanceTimersByTimeAsync(JOB_POLL_MS);
    http.expectOne(ACTIVITY_URL).flush(FAILED_JOB);
    expect(store.jobs().get(ACTIVITY_ID)?.job?.error_code).toBe('ssh_unreachable');

    await vi.advanceTimersByTimeAsync(JOB_POLL_MS * 2);
    http.expectNone(ACTIVITY_URL);
  });

  it('clears the log and stops following its jobs, but keeps the history', async () => {
    const running = store.run('backup take shop');
    consoleRequest().flush(STARTED);
    await running;
    await vi.advanceTimersByTimeAsync(0);
    http.expectOne(ACTIVITY_URL).flush(RUNNING_JOB);

    store.clear();

    expect(store.entries()).toEqual([]);
    expect(store.jobs().size).toBe(0);
    expect(store.history()).toEqual(['backup take shop']);
    await vi.advanceTimersByTimeAsync(JOB_POLL_MS * 2);
    http.expectNone(ACTIVITY_URL);
  });

  it('forgets the log, the history and the jobs when the account changes', async () => {
    await signIn();
    const running = store.run('backup take shop');
    consoleRequest().flush(STARTED);
    await running;
    await vi.advanceTimersByTimeAsync(0);
    http.expectOne(ACTIVITY_URL).flush(RUNNING_JOB);

    TestBed.inject(AuthStore).forget();
    TestBed.tick();

    expect(store.entries()).toEqual([]);
    expect(store.history()).toEqual([]);
    expect(store.jobs().size).toBe(0);
    await vi.advanceTimersByTimeAsync(JOB_POLL_MS * 2);
    http.expectNone(ACTIVITY_URL);
  });

  it(`keeps the last ${CONSOLE_HISTORY_MAX} commands, once each when repeated in a row`, async () => {
    const runAll = async (lines: readonly string[]): Promise<void> => {
      for (const line of lines) {
        const running = store.run(line);
        consoleRequest().flush(LISTED);
        await running;
      }
    };

    await runAll(['server list', 'server list']);
    expect(store.history()).toEqual(['server list']);

    await runAll(Array.from({ length: CONSOLE_HISTORY_MAX }, (_, n) => `app show ${n}`));
    expect(store.history()).toHaveLength(CONSOLE_HISTORY_MAX);
    expect(store.history()[0]).toBe('app show 0');
    expect(store.history().at(-1)).toBe(`app show ${CONSOLE_HISTORY_MAX - 1}`);
  });
});
