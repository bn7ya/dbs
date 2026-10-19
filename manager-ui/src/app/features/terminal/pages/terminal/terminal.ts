import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
  untracked,
  viewChild,
  type Signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';
import { MatButton } from '@angular/material/button';

import { routeParam } from '@core/routing/route-param';
import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { Dialogs } from '@shared/dialogs/dialogs';
import { isolated } from '@shared/isolated/isolated';
import { Notice } from '@shared/notice/notice';
import { PasswordPrompt } from '@shared/password-prompt/password-prompt';
import type { PasswordPromptData } from '@shared/password-prompt/password-prompt.types';
import { StatusTag } from '@shared/status-tag/status-tag';
import { TerminalView } from '@shared/terminal-view/terminal-view';
import type { TerminalSize } from '@shared/terminal-view/terminal-view.types';
import { uniqueId } from '@shared/unique-id';
import type { Terminal, TerminalMode } from '../../data/terminals.types';
import { TerminalStore } from '../../state/terminal.store';
import type { TerminalFeed, TerminalPlace, TerminalWhere } from '../../state/terminal.store.types';
import type { EndNotice, TranslatedLine } from './terminal.types';

const PARAMETER: Readonly<Record<TerminalMode, string>> = {
  server: 'serverId',
  application: 'applicationId',
};

const QUIET_ENDINGS: ReadonlySet<string> = new Set(['exited', 'closed']);

@Component({
  selector: 'app-terminal-page',
  imports: [MatButton, Notice, StatusTag, TerminalView, ErrorTextPipe, TranslatePipe],
  providers: [Dialogs],
  templateUrl: './terminal.html',
  styleUrl: './terminal.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TerminalPage {
  private readonly store = inject(TerminalStore);
  private readonly dialogs = inject(Dialogs);
  private readonly locale = inject(LocaleStore);
  private readonly route = inject(ActivatedRoute);

  private readonly mode = modeOf(this.route);
  private readonly placeId: Signal<string | null> =
    this.mode === null ? signal(null).asReadonly() : routeParam(this.route, PARAMETER[this.mode]);

  readonly place = computed<TerminalPlace | null>(() => {
    const id = this.placeId();
    return this.mode === null || id === null ? null : { mode: this.mode, id };
  });

  private readonly view = viewChild.required(TerminalView);

  readonly headingId = uniqueId('terminal-heading');

  readonly where = this.store.where;
  readonly whereError = this.store.whereError;
  readonly attached = this.store.attached;
  readonly reattachable = this.store.reattachable;
  readonly opening = this.store.opening;
  readonly closing = this.store.closing;
  readonly discarding = this.store.discarding;
  readonly error = this.store.error;
  readonly skipped = this.store.skipped;
  readonly reattached = this.store.reattached;

  readonly whereLine = computed<TranslatedLine | null>(() => {
    const where = this.where();
    return where === null ? null : lineOf(where);
  });

  readonly viewLabel = computed(() => {
    const name = this.where()?.name;
    return name === undefined
      ? this.locale.translate('terminal.view.unnamed')
      : this.locale.translate('terminal.view.named', { name: isolated(name) });
  });

  readonly endNotice = computed<EndNotice | null>(() => {
    const end = this.store.ended();
    if (end === null) {
      return null;
    }
    if (end.reason === null) {
      return { severity: 'warning', line: null, error: end.error };
    }
    const line: TranslatedLine =
      end.reason === 'exited' && end.exitStatus !== null
        ? { key: 'terminal.ended.exitedWith', values: { status: end.exitStatus } }
        : { key: `terminal.ended.${end.reason}` };
    return { severity: QUIET_ENDINGS.has(end.reason) ? 'info' : 'warning', line, error: null };
  });

  constructor() {
    effect(() => {
      const place = this.place();
      if (place !== null) {
        untracked(() => this.store.enter(place));
      }
    });
    inject(DestroyRef).onDestroy(() => this.store.leave());
    this.store.output.pipe(takeUntilDestroyed()).subscribe((feed) => this.show(feed));
  }

  async open(): Promise<void> {
    const name = this.where()?.name;
    const data: PasswordPromptData = {
      titleKey: 'terminal.prompt.title',
      bodyKey: name === undefined ? 'terminal.prompt.body' : 'terminal.prompt.bodyNamed',
      bodyValues: name === undefined ? undefined : { name: isolated(name) },
      submitKey: 'terminal.prompt.submit',
      submit: (password) => this.store.open(password),
      error: this.store.passwordError,
    };
    await this.dialogs
      .open<boolean, PasswordPromptData>(PasswordPrompt, { titleKey: data.titleKey, data, size: 'sm' })
      .whenClosed();
    if (this.attached()) {
      this.view().focus();
    }
  }

  reattach(terminal: Terminal): void {
    this.store.reattach(terminal);
    this.view().focus();
  }

  discard(terminal: Terminal): void {
    this.store.discard(terminal);
  }

  close(): void {
    this.store.close();
  }

  dismissError(): void {
    this.store.dismissError();
  }

  retryWhere(): void {
    this.store.retryWhere();
  }

  type(data: string): void {
    this.store.type(data);
  }

  resize(size: TerminalSize): void {
    this.store.resize(size);
  }

  private show(feed: TerminalFeed): void {
    if (feed.kind === 'reset') {
      this.view().clear();
    } else {
      this.view().write(feed.bytes);
    }
  }
}

function modeOf(route: ActivatedRoute): TerminalMode | null {
  const mode: unknown = route.snapshot.data['mode'];
  return mode === 'server' || mode === 'application' ? mode : null;
}

function lineOf(where: TerminalWhere): TranslatedLine {
  switch (where.kind) {
    case 'server':
      return { key: 'terminal.where.server', values: { name: isolated(where.name), user: isolated(where.username) } };
    case 'compose':
      return { key: 'terminal.where.compose', values: { name: isolated(where.name), service: isolated(where.service) } };
    case 'container':
      return {
        key: 'terminal.where.container',
        values: { name: isolated(where.name), container: isolated(where.container) },
      };
    case 'host':
      return where.folder === ''
        ? { key: 'terminal.where.home', values: { name: isolated(where.name) } }
        : { key: 'terminal.where.host', values: { name: isolated(where.name), folder: isolated(where.folder) } };
  }
}
