import { Injectable, computed, inject, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import {
  EMPTY,
  Subject,
  Subscription,
  bufferTime,
  catchError,
  concatMap,
  debounceTime,
  distinctUntilChanged,
  expand,
  filter,
  finalize,
  firstValueFrom,
  from,
  map,
  retry,
  skip,
  startWith,
  switchMap,
  throwError,
  timer,
  type Observable,
} from 'rxjs';

import { AuthStore } from '@core/auth/state/auth.store';
import { apiErrorOf } from '@core/http/api-error';
import type { ApiError } from '@core/http/api.types';
import type { TerminalSize } from '@shared/terminal-view/terminal-view.types';
import { TerminalsApi } from '../data/terminals.api';
import {
  TERMINAL_COLS,
  TERMINAL_INPUT_MAX_BYTES,
  TERMINAL_ROWS,
  type Terminal,
  type TerminalApplication,
  type TerminalOutput,
} from '../data/terminals.types';
import type { TerminalEnd, TerminalFeed, TerminalPlace, TerminalWhere } from './terminal.store.types';

export const TERMINAL_INPUT_BATCH_MS = 30;
export const TERMINAL_RESIZE_DEBOUNCE_MS = 200;
export const TERMINAL_QUIET_POLL_MS = 250;
export const TERMINAL_RETRY_MS = 1000;
export const TERMINAL_RETRIES = 4;

const DEFAULT_SIZE: TerminalSize = { cols: 80, rows: 24 };
const TRANSIENT: ReadonlySet<string> = new Set(['network', 'unknown']);
const PASSWORD_FAILURES: ReadonlySet<string> = new Set(['invalid_password', 'too_many_attempts']);
const GONE: ReadonlySet<string> = new Set(['terminal_closed', 'terminal_not_found']);

@Injectable()
export class TerminalStore {
  private readonly api = inject(TerminalsApi);
  private readonly auth = inject(AuthStore);

  readonly place = signal<TerminalPlace | null>(null);

  private readonly whereResource = rxResource({
    params: () => this.place() ?? undefined,
    stream: ({ params }) => this.whereOf(params),
  });

  readonly where = computed(() => (this.whereResource.hasValue() ? this.whereResource.value() : null));
  readonly whereError = computed(() => apiErrorOf(this.whereResource.error()));

  private readonly openResource = rxResource({
    params: () => this.place() ?? undefined,
    stream: () => this.api.list(),
  });

  readonly session = signal<Terminal | null>(null);
  readonly attached = computed(() => this.session() !== null);

  readonly reattachable = computed<readonly Terminal[]>(() => {
    const place = this.place();
    if (place === null || this.attached() || !this.openResource.hasValue()) {
      return [];
    }
    return this.openResource.value().filter((terminal) => !terminal.closed && isAt(terminal, place));
  });

  readonly opening = signal(false);
  readonly closing = signal(false);
  readonly discarding = signal<string | null>(null);
  readonly passwordError = signal<ApiError | null>(null);
  readonly error = signal<ApiError | null>(null);
  readonly ended = signal<TerminalEnd | null>(null);
  readonly skipped = signal(false);
  readonly reattached = signal(false);

  private readonly feed = new Subject<TerminalFeed>();
  readonly output: Observable<TerminalFeed> = this.feed.asObservable();

  private readonly keystrokes = new Subject<string>();
  private readonly sizes = new Subject<TerminalSize>();
  private readonly viewSize = signal<TerminalSize>(DEFAULT_SIZE);
  private attachment = Subscription.EMPTY;
  private seq = 0;

  enter(place: TerminalPlace): void {
    const current = this.place();
    if (current !== null && current.mode === place.mode && current.id === place.id) {
      return;
    }
    this.leave();
    this.place.set(place);
  }

  leave(): void {
    const session = this.session();
    this.detach();
    this.session.set(null);
    this.place.set(null);
    this.ended.set(null);
    this.error.set(null);
    this.passwordError.set(null);
    this.skipped.set(false);
    this.reattached.set(false);
    if (session !== null && this.auth.isAuthenticated()) {
      this.api.close(session.id).subscribe({ error: () => undefined });
    }
  }

  async open(password: string): Promise<boolean> {
    const place = this.place();
    if (place === null || this.attached()) {
      return true;
    }
    this.opening.set(true);
    this.passwordError.set(null);
    this.error.set(null);
    try {
      const terminal = await firstValueFrom(
        this.api.open({ mode: place.mode, ...placeField(place), password, ...this.viewSize() }),
      );
      if (this.place() === place) {
        this.attach(terminal, false);
      } else {
        this.api.close(terminal.id).subscribe({ error: () => undefined });
      }
      return true;
    } catch (error) {
      const failure = error as ApiError;
      if (PASSWORD_FAILURES.has(failure.code)) {
        this.passwordError.set(failure);
        return false;
      }
      this.error.set(failure);
      return true;
    } finally {
      this.opening.set(false);
    }
  }

  reattach(terminal: Terminal): void {
    this.error.set(null);
    this.attach(terminal, true);
  }

  close(): void {
    const session = this.session();
    if (session === null || this.closing()) {
      return;
    }
    this.closing.set(true);
    this.api
      .close(session.id)
      .pipe(finalize(() => this.closing.set(false)))
      .subscribe({
        complete: () => this.finish(session, { reason: 'closed', exitStatus: null, error: null }),
        error: (error: ApiError) =>
          GONE.has(error.code) ? this.finish(session, ended(error)) : this.error.set(error),
      });
  }

  discard(terminal: Terminal): void {
    if (this.discarding() !== null) {
      return;
    }
    this.discarding.set(terminal.id);
    this.api
      .close(terminal.id)
      .pipe(
        finalize(() => {
          this.discarding.set(null);
          this.openResource.reload();
        }),
      )
      .subscribe({
        error: (error: ApiError) => {
          if (!GONE.has(error.code)) {
            this.error.set(error);
          }
        },
      });
  }

  type(data: string): void {
    this.keystrokes.next(data);
  }

  resize(size: TerminalSize): void {
    const fitted = clamped(size);
    this.viewSize.set(fitted);
    this.sizes.next(fitted);
  }

  dismissError(): void {
    this.error.set(null);
  }

  retryWhere(): void {
    this.whereResource.reload();
  }

  private attach(terminal: Terminal, reattached: boolean): void {
    this.detach();
    this.session.set(terminal);
    this.ended.set(null);
    this.skipped.set(false);
    this.reattached.set(reattached);
    this.feed.next({ kind: 'reset' });
    const attachment = new Subscription();
    attachment.add(
      this.outputOf(terminal.id)
        .pipe(map((output, index) => (reattached && index === 0 ? { ...output, skipped: false } : output)))
        .subscribe({
          next: (output) => this.show(terminal, output),
          error: (error: ApiError) => this.finish(terminal, ended(error)),
        }),
    );
    attachment.add(this.inputOf(terminal.id).subscribe());
    attachment.add(this.resizesOf(terminal).subscribe((resized) => this.session.set(resized)));
    this.attachment = attachment;
    this.sizes.next(this.viewSize());
  }

  private detach(): void {
    this.attachment.unsubscribe();
    this.attachment = Subscription.EMPTY;
  }

  private show(terminal: Terminal, output: TerminalOutput): void {
    if (output.skipped) {
      this.skipped.set(true);
    }
    if (output.bytes.length > 0) {
      this.feed.next({ kind: 'data', bytes: output.bytes });
    }
    if (output.closed) {
      this.finish(terminal, { reason: output.reason, exitStatus: output.exitStatus, error: null });
    }
  }

  private finish(terminal: Terminal, end: TerminalEnd): void {
    if (this.session()?.id !== terminal.id) {
      return;
    }
    this.detach();
    this.session.set(null);
    this.reattached.set(false);
    this.ended.set(end);
    this.openResource.reload();
  }

  private outputOf(id: string): Observable<TerminalOutput> {
    const read = (cursor: number): Observable<TerminalOutput> =>
      this.api.output(id, cursor).pipe(retry({ count: TERMINAL_RETRIES, delay: retryTransient }));
    // A quiet answer may come back at once while another reader holds the long poll, so it waits a beat.
    return read(0).pipe(
      expand((output) => {
        if (output.closed) {
          return EMPTY;
        }
        const quiet = output.bytes.length === 0 && !output.skipped;
        return quiet ? timer(TERMINAL_QUIET_POLL_MS).pipe(switchMap(() => read(output.cursor))) : read(output.cursor);
      }),
    );
  }

  private inputOf(id: string): Observable<unknown> {
    return this.keystrokes.pipe(
      bufferTime(TERMINAL_INPUT_BATCH_MS),
      filter((keys) => keys.length > 0),
      concatMap((keys) => from(chunksOf(keys.join(''), TERMINAL_INPUT_MAX_BYTES))),
      concatMap((data) => this.send(id, data)),
    );
  }

  private send(id: string, data: string): Observable<unknown> {
    const seq = this.nextSeq();
    return this.api.input(id, seq, data).pipe(
      retry({ count: TERMINAL_RETRIES, delay: retryTransient }),
      catchError(() => EMPTY),
    );
  }

  // The backend skips a seq it already took and never says which it took last, so a page that
  // reattaches starts from the clock, above anything an earlier page could have sent.
  private nextSeq(): number {
    this.seq = Math.max(this.seq + 1, Date.now());
    return this.seq;
  }

  private resizesOf(terminal: Terminal): Observable<Terminal> {
    return this.sizes.pipe(
      debounceTime(TERMINAL_RESIZE_DEBOUNCE_MS),
      startWith({ cols: terminal.cols, rows: terminal.rows }),
      distinctUntilChanged(sameSize),
      skip(1),
      switchMap((size) => this.api.resize(terminal.id, size).pipe(catchError(() => EMPTY))),
    );
  }

  private whereOf(place: TerminalPlace): Observable<TerminalWhere> {
    if (place.mode === 'server') {
      return this.api
        .server(place.id)
        .pipe(map((server): TerminalWhere => ({ kind: 'server', name: server.name, username: server.username })));
    }
    return this.api.application(place.id).pipe(map(whereOfApplication));
  }
}

function placeField(place: TerminalPlace): { server: string } | { application: string } {
  return place.mode === 'server' ? { server: place.id } : { application: place.id };
}

function isAt(terminal: Terminal, place: TerminalPlace): boolean {
  if (terminal.mode !== place.mode) {
    return false;
  }
  return place.mode === 'server' ? terminal.server === place.id : terminal.application === place.id;
}

function whereOfApplication(application: TerminalApplication): TerminalWhere {
  switch (application.kind) {
    case 'compose':
      return { kind: 'compose', name: application.name, service: application.compose_service };
    case 'container':
      return { kind: 'container', name: application.name, container: application.container_name };
    default:
      return { kind: 'host', name: application.name, folder: application.project_dir };
  }
}

function ended(error: ApiError): TerminalEnd {
  return { reason: null, exitStatus: null, error };
}

function retryTransient(error: unknown, attempt: number): Observable<number> {
  const code = (error as ApiError | null)?.code ?? '';
  return TRANSIENT.has(code) ? timer(attempt * TERMINAL_RETRY_MS) : throwError(() => error);
}

function clamped(size: TerminalSize): TerminalSize {
  return {
    cols: Math.min(TERMINAL_COLS.max, Math.max(TERMINAL_COLS.min, Math.floor(size.cols))),
    rows: Math.min(TERMINAL_ROWS.max, Math.max(TERMINAL_ROWS.min, Math.floor(size.rows))),
  };
}

function sameSize(one: TerminalSize, other: TerminalSize): boolean {
  return one.cols === other.cols && one.rows === other.rows;
}

function chunksOf(text: string, limit: number): string[] {
  const chunks: string[] = [];
  let current = '';
  let size = 0;
  for (const character of text) {
    const bytes = utf8Length(character);
    if (size + bytes > limit) {
      chunks.push(current);
      current = '';
      size = 0;
    }
    current += character;
    size += bytes;
  }
  if (current !== '') {
    chunks.push(current);
  }
  return chunks;
}

function utf8Length(character: string): number {
  const point = character.codePointAt(0) ?? 0;
  if (point < 0x80) {
    return 1;
  }
  if (point < 0x800) {
    return 2;
  }
  return point < 0x10000 ? 3 : 4;
}
