import { DestroyRef, Injectable, computed, effect, inject, linkedSignal, signal, untracked } from '@angular/core';
import { Subscription, firstValueFrom } from 'rxjs';

import { AuthStore } from '@core/auth/state/auth.store';
import type { ApiError } from '@core/http/api.types';
import { JobWatcher } from '@core/jobs/job-watcher';
import { ConsoleApi } from '../data/console.api';
import type { ConsoleResult } from '../data/console.types';
import type { ConsoleEntry, ConsoleJob } from './console.store.types';

export const CONSOLE_HISTORY_MAX = 100;

const PASSWORD_FAILURES: ReadonlySet<string> = new Set(['invalid_password', 'too_many_attempts']);
const LINE_FIELD = 'line';

@Injectable()
export class ConsoleStore {
  private readonly api = inject(ConsoleApi);
  private readonly watcher = inject(JobWatcher);
  private readonly auth = inject(AuthStore);

  private readonly account = computed(() => this.auth.user()?.id ?? null);

  private readonly log = linkedSignal<number | null, readonly ConsoleEntry[]>({
    source: this.account,
    computation: () => [],
  });
  private readonly typed = linkedSignal<number | null, readonly string[]>({
    source: this.account,
    computation: () => [],
  });
  private readonly followed = linkedSignal<number | null, ReadonlyMap<number, ConsoleJob>>({
    source: this.account,
    computation: () => new Map(),
  });

  readonly entries = this.log.asReadonly();
  readonly history = this.typed.asReadonly();
  readonly jobs = this.followed.asReadonly();
  readonly busy = signal(false);
  readonly passwordError = signal<ApiError | null>(null);

  private watching = new Subscription();
  private watchingFor = untracked(this.account);
  private lastId = 0;

  constructor() {
    effect(() => {
      this.account();
      untracked(() => this.watchers());
    });
    inject(DestroyRef).onDestroy(() => this.watching.unsubscribe());
  }

  async run(line: string): Promise<ConsoleEntry | null> {
    const command = line.trim();
    if (command === '' || this.busy()) {
      return null;
    }
    this.remember(command);
    this.lastId += 1;
    const id = this.lastId;
    this.log.update((entries) => [...entries, started(id, command)]);
    this.busy.set(true);
    try {
      return this.settle(id, await firstValueFrom(this.api.run({ line: command })));
    } catch (error) {
      return this.change(id, { state: 'refused', error: lineError(error as ApiError) });
    } finally {
      this.busy.set(false);
    }
  }

  async runWithPassword(entry: ConsoleEntry, password: string): Promise<boolean> {
    if (this.busy()) {
      return false;
    }
    this.passwordError.set(null);
    this.busy.set(true);
    try {
      const result = await firstValueFrom(this.api.run({ line: entry.line, password }));
      if (PASSWORD_FAILURES.has(result.error_code)) {
        this.passwordError.set({ code: result.error_code, message: '' });
        return false;
      }
      this.settle(entry.id, result);
      return true;
    } catch (error) {
      this.passwordError.set(lineError(error as ApiError));
      return false;
    } finally {
      this.busy.set(false);
    }
  }

  clear(): void {
    this.stopWatching();
    this.log.set([]);
    this.followed.set(new Map());
  }

  private settle(id: number, result: ConsoleResult): ConsoleEntry | null {
    const settled = this.change(id, {
      state: result.password_required ? 'password' : 'done',
      exitCode: result.exit_code,
      output: result.output,
      activities: result.activities,
      errorCode: result.error_code,
    });
    if (settled !== null) {
      this.follow(result.activities);
    }
    return settled;
  }

  private change(id: number, changes: Partial<ConsoleEntry>): ConsoleEntry | null {
    const entry = this.log().find((each) => each.id === id);
    if (entry === undefined) {
      return null;
    }
    const changed: ConsoleEntry = { ...entry, ...changes };
    this.log.update((entries) => entries.map((each) => (each.id === id ? changed : each)));
    return changed;
  }

  private follow(activities: readonly number[]): void {
    for (const id of activities) {
      if (this.followed().has(id)) {
        continue;
      }
      this.record({ id, job: null, error: null });
      this.watchers().add(
        this.watcher.watch(id).subscribe({
          next: (job) => this.record({ id, job, error: null }),
          error: (error: ApiError) => this.record({ id, job: null, error }),
        }),
      );
    }
  }

  private record(job: ConsoleJob): void {
    this.followed.update((jobs) => new Map(jobs).set(job.id, job));
  }

  private remember(command: string): void {
    this.typed.update((history) =>
      history.at(-1) === command ? history : [...history, command].slice(-CONSOLE_HISTORY_MAX),
    );
  }

  private watchers(): Subscription {
    const account = this.account();
    if (account !== this.watchingFor) {
      this.watchingFor = account;
      this.stopWatching();
    }
    return this.watching;
  }

  private stopWatching(): void {
    this.watching.unsubscribe();
    this.watching = new Subscription();
  }
}

function started(id: number, line: string): ConsoleEntry {
  return { id, line, state: 'running', exitCode: null, output: '', activities: [], errorCode: '', error: null };
}

function lineError(error: ApiError): ApiError {
  const code = error.fields?.[LINE_FIELD]?.[0];
  return code === undefined ? error : { code, message: error.message };
}
