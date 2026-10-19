import { ChangeDetectionStrategy, Component, booleanAttribute, computed, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButton } from '@angular/material/button';
import { MatError, MatFormField, MatHint, MatLabel } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';

import { Can } from '@core/auth/directives/can';
import type { ApiError } from '@core/http/api.types';
import { ErrorTextPipe, errorText } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { FieldError } from '@shared/field/field-error';
import { isolated } from '@shared/isolated/isolated';
import { Notice } from '@shared/notice/notice';
import { PasswordInput } from '@shared/password-input/password-input';
import type { RunRequest } from '../../data/redeploy.types';
import type { RunAttempt } from './confirmed-run.types';

const FIELD_FAILURES: ReadonlySet<string> = new Set(['invalid_password', 'confirm_name_mismatch']);

const REHEARSAL: RunRequest = { rehearsal: true, password: '', confirm_name: '' };

@Component({
  selector: 'app-confirmed-run',
  imports: [
    Can,
    FormsModule,
    MatButton,
    MatError,
    MatFormField,
    MatHint,
    MatInput,
    MatLabel,
    FieldError,
    Notice,
    PasswordInput,
    ErrorTextPipe,
    TranslatePipe,
  ],
  templateUrl: './confirmed-run.html',
  styleUrl: './confirmed-run.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ConfirmedRun {
  private readonly locale = inject(LocaleStore);

  readonly prefix = input.required<string>();
  readonly expectedName = input.required<string>();
  readonly busy = input(false);
  readonly rehearsing = input(false);
  readonly error = input<ApiError | null>(null);
  readonly ready = input(true);
  readonly primary = input(false, { transform: booleanAttribute });

  readonly attempted = output<RunAttempt>();
  readonly run = output<RunRequest>();
  readonly edited = output();

  readonly password = signal('');
  readonly typedName = signal('');
  private readonly attempt = signal<RunAttempt | null>(null);

  readonly nameHint = computed(() => {
    const name = this.expectedName();
    return name === '' ? '' : this.locale.translate(`${this.prefix()}.confirmNameHint`, { name: isolated(name) });
  });

  readonly passwordError = computed(() => {
    if (this.attempt() === 'real' && this.password() === '') {
      return this.locale.translate('password.required');
    }
    return this.error()?.code === 'invalid_password' ? errorText(this.locale, 'invalid_password') : '';
  });

  readonly nameError = computed(() => {
    const expected = this.expectedName();
    if (this.attempt() === 'real' && expected !== '' && this.typedName().trim() !== expected) {
      return errorText(this.locale, 'confirm_name_mismatch');
    }
    return this.error()?.code === 'confirm_name_mismatch' ? errorText(this.locale, 'confirm_name_mismatch') : '';
  });

  readonly failure = computed(() => {
    const failure = this.error();
    return failure && !FIELD_FAILURES.has(failure.code) ? failure : null;
  });

  readonly rehearsalBusy = computed(() => this.busy() && this.rehearsing());
  readonly realBusy = computed(() => this.busy() && !this.rehearsing());

  setPassword(value: string): void {
    this.password.set(value);
    this.edited.emit();
  }

  setTypedName(value: string): void {
    this.typedName.set(value);
    this.edited.emit();
  }

  rehearse(): void {
    this.attempt.set('rehearsal');
    this.attempted.emit('rehearsal');
    if (this.ready() && !this.busy()) {
      this.run.emit(REHEARSAL);
    }
  }

  runForReal(): void {
    this.attempt.set('real');
    this.attempted.emit('real');
    if (!this.ready() || this.busy() || this.passwordError() !== '' || this.nameError() !== '') {
      return;
    }
    this.run.emit({ rehearsal: false, password: this.password(), confirm_name: this.typedName().trim() });
  }
}
