import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  afterRenderEffect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { MatButton } from '@angular/material/button';
import { MatFormField, MatHint, MatLabel, MatPrefix } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { JobStatus } from '@core/jobs/job.types';
import { Dialogs } from '@shared/dialogs/dialogs';
import { isolated } from '@shared/isolated/isolated';
import { PasswordPrompt } from '@shared/password-prompt/password-prompt';
import type { PasswordPromptData } from '@shared/password-prompt/password-prompt.types';
import { StatusTag } from '@shared/status-tag/status-tag';
import { ConsoleStore } from '../../state/console.store';
import type { ConsoleEntry, ConsoleJob } from '../../state/console.store.types';
import type { StatusLook } from './console.types';

const PROGRAM = 'django_dbs';
const PROMPT = '$';
const HELP = 'help';

const RUNNING: StatusLook = { severity: 'info', icon: 'fa-solid fa-spinner fa-spin', labelKey: 'console.state.running' };
const NEEDS_PASSWORD: StatusLook = { severity: 'warning', icon: 'fa-solid fa-key', labelKey: 'console.state.password' };
const REFUSED: StatusLook = { severity: 'danger', icon: 'fa-solid fa-ban', labelKey: 'console.state.refused' };
const STARTING: StatusLook = { severity: 'neutral', icon: 'fa-regular fa-clock', labelKey: 'console.job.starting' };
const UNREADABLE: StatusLook = { severity: 'warning', icon: 'fa-solid fa-circle-question', labelKey: 'console.job.unreadable' };

const JOB_LOOKS: Readonly<Record<JobStatus, StatusLook>> = {
  queued: { severity: 'neutral', icon: 'fa-regular fa-clock', labelKey: 'console.job.queued' },
  running: { severity: 'info', icon: 'fa-solid fa-spinner fa-spin', labelKey: 'console.job.running' },
  succeeded: { severity: 'success', icon: 'fa-solid fa-circle-check', labelKey: 'console.job.succeeded' },
  failed: { severity: 'danger', icon: 'fa-solid fa-circle-xmark', labelKey: 'console.job.failed' },
};

@Component({
  selector: 'app-console-page',
  imports: [
    FormsModule,
    RouterLink,
    MatButton,
    MatFormField,
    MatHint,
    MatInput,
    MatLabel,
    MatPrefix,
    StatusTag,
    ErrorTextPipe,
    TranslatePipe,
  ],
  providers: [Dialogs],
  templateUrl: './console.html',
  styleUrl: './console.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ConsolePage {
  private readonly store = inject(ConsoleStore);
  private readonly dialogs = inject(Dialogs);
  private readonly locale = inject(LocaleStore);

  readonly program = PROGRAM;
  readonly prompt = PROMPT;
  readonly direction = this.locale.direction;

  readonly entries = this.store.entries;
  readonly busy = this.store.busy;

  readonly line = signal('');
  private readonly recalled = signal<number | null>(null);
  private readonly draft = signal('');

  private readonly log = viewChild.required<ElementRef<HTMLElement>>('log');
  private readonly field = viewChild.required<ElementRef<HTMLInputElement>>('field');

  constructor() {
    afterRenderEffect(() => {
      this.entries();
      this.store.jobs();
      const log = this.log().nativeElement;
      log.scrollTop = log.scrollHeight;
    });
  }

  async run(): Promise<void> {
    const line = this.line();
    if (line.trim() === '' || this.busy()) {
      return;
    }
    this.line.set('');
    this.recalled.set(null);
    await this.execute(line);
  }

  help(): Promise<void> {
    return this.execute(HELP);
  }

  clear(): void {
    this.store.clear();
    this.field().nativeElement.focus();
  }

  previous(event: Event): void {
    const history = this.store.history();
    if (history.length === 0) {
      return;
    }
    event.preventDefault();
    const at = this.recalled();
    if (at === null) {
      this.draft.set(this.line());
    }
    const index = at === null ? history.length - 1 : Math.max(0, at - 1);
    this.recalled.set(index);
    this.line.set(history[index]);
  }

  next(event: Event): void {
    const at = this.recalled();
    if (at === null) {
      return;
    }
    event.preventDefault();
    const history = this.store.history();
    if (at + 1 >= history.length) {
      this.recalled.set(null);
      this.line.set(this.draft());
      return;
    }
    this.recalled.set(at + 1);
    this.line.set(history[at + 1]);
  }

  async askPassword(entry: ConsoleEntry): Promise<void> {
    const data: PasswordPromptData = {
      titleKey: 'console.password.title',
      bodyKey: 'console.password.body',
      bodyValues: { command: isolated(`${PROGRAM} ${entry.line}`) },
      submitKey: 'console.password.submit',
      submit: (password) => this.store.runWithPassword(entry, password),
      error: this.store.passwordError,
    };
    await this.dialogs
      .open<boolean, PasswordPromptData>(PasswordPrompt, { titleKey: data.titleKey, data, size: 'sm' })
      .whenClosed();
    this.field().nativeElement.focus();
  }

  look(entry: ConsoleEntry): StatusLook {
    switch (entry.state) {
      case 'running':
        return RUNNING;
      case 'password':
        return NEEDS_PASSWORD;
      case 'refused':
        return REFUSED;
      case 'done':
        return entry.exitCode === 0
          ? { severity: 'success', icon: 'fa-solid fa-circle-check', labelKey: 'console.state.done', values: { code: 0 } }
          : {
              severity: 'danger',
              icon: 'fa-solid fa-circle-xmark',
              labelKey: 'console.state.failed',
              values: { code: entry.exitCode ?? '' },
            };
    }
  }

  failed(entry: ConsoleEntry): boolean {
    return entry.state === 'refused' || (entry.state === 'done' && entry.exitCode !== 0);
  }

  explained(entry: ConsoleEntry): boolean {
    return entry.errorCode !== '' && this.locale.has(`errors.${entry.errorCode}`);
  }

  job(id: number): ConsoleJob | null {
    return this.store.jobs().get(id) ?? null;
  }

  jobLook(followed: ConsoleJob | null): StatusLook {
    if (followed?.error) {
      return UNREADABLE;
    }
    return followed?.job ? JOB_LOOKS[followed.job.status] : STARTING;
  }

  private async execute(line: string): Promise<void> {
    const entry = await this.store.run(line);
    if (entry?.state === 'password') {
      await this.askPassword(entry);
    }
  }
}
