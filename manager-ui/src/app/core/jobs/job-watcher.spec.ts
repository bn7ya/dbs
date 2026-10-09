import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, type TestRequest } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import type { Subscription } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ApiError } from '@core/http/api.types';
import { errorInterceptor } from '@core/http/error.interceptor';
import { JOB_POLL_MS, JobWatcher } from './job-watcher';
import type { Job } from './job.types';

const ID = '7a1e0c55-2222-4d1b-8f00-9c3e5b7d0001';
const URL = `/api/activity/${ID}/`;

const RUNNING: Job = {
  id: ID,
  action: 'backup.take',
  status: 'running',
  detail: {},
  error_code: '',
  finished_at: null,
};

const SUCCEEDED: Job = {
  ...RUNNING,
  status: 'succeeded',
  detail: { backup: 'b-1', size: 2048 },
  finished_at: '2026-09-30T12:01:00Z',
};

describe('JobWatcher', () => {
  let watcher: JobWatcher;
  let http: HttpTestingController;
  let subscription: Subscription | undefined;

  let seen: Job[];
  let completed: boolean;
  let failure: ApiError | undefined;

  const follow = (): void => {
    subscription = watcher.watch(ID).subscribe({
      next: (job) => seen.push(job),
      complete: () => (completed = true),
      error: (error: ApiError) => (failure = error),
    });
  };

  const read = (): TestRequest => http.expectOne(URL);

  beforeEach(() => {
    vi.useFakeTimers();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    watcher = TestBed.inject(JobWatcher);
    http = TestBed.inject(HttpTestingController);
    seen = [];
    completed = false;
    failure = undefined;
  });

  afterEach(() => {
    subscription?.unsubscribe();
    http.verify();
    TestBed.resetTestingModule();
    vi.useRealTimers();
  });

  it('reads the job at once, then every interval, and completes once it has finished', () => {
    follow();
    vi.advanceTimersByTime(0);
    read().flush({ ...RUNNING, status: 'queued' });
    expect(seen.map((job) => job.status)).toEqual(['queued']);

    vi.advanceTimersByTime(JOB_POLL_MS - 1);
    http.expectNone(URL);
    vi.advanceTimersByTime(1);
    read().flush(RUNNING);

    vi.advanceTimersByTime(JOB_POLL_MS);
    read().flush(SUCCEEDED);

    expect(seen.map((job) => job.status)).toEqual(['queued', 'running', 'succeeded']);
    expect(seen.at(-1)).toEqual(SUCCEEDED);
    expect(completed).toBe(true);

    vi.advanceTimersByTime(JOB_POLL_MS * 3);
    http.expectNone(URL);
  });

  it('ends with a failed job as its last value, not as an error', () => {
    follow();
    vi.advanceTimersByTime(0);
    read().flush({ ...RUNNING, status: 'failed', error_code: 'ssh_unreachable' });

    expect(seen.at(-1)?.error_code).toBe('ssh_unreachable');
    expect(completed).toBe(true);
    expect(failure).toBeUndefined();
  });

  it('waits for a slow read rather than asking again over it', () => {
    follow();
    vi.advanceTimersByTime(0);
    const slow = read();

    vi.advanceTimersByTime(JOB_POLL_MS * 2);
    http.expectNone(URL);
    expect(slow.cancelled).toBe(false);

    slow.flush(RUNNING);
    vi.advanceTimersByTime(JOB_POLL_MS);
    read().flush(SUCCEEDED);
    expect(completed).toBe(true);
  });

  it('ends with the ApiError when a read fails', () => {
    follow();
    vi.advanceTimersByTime(0);
    read().flush({ error: { code: 'not_found', message: 'Server prose' } }, { status: 404, statusText: 'Not Found' });

    expect(failure?.code).toBe('not_found');
    vi.advanceTimersByTime(JOB_POLL_MS * 2);
    http.expectNone(URL);
  });

  it('stops reading once nobody follows it', () => {
    follow();
    vi.advanceTimersByTime(0);
    read().flush(RUNNING);

    subscription?.unsubscribe();
    vi.advanceTimersByTime(JOB_POLL_MS * 3);
    http.expectNone(URL);
  });
});
