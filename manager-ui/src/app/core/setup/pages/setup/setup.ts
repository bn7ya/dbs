import { ChangeDetectionStrategy, Component, computed, inject, input, linkedSignal, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { MatError, MatFormField, MatHint, MatLabel } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';
import { Router, RouterLink } from '@angular/router';

import { AuthStore } from '@core/auth/state/auth.store';
import { errorText, ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { LocaleSwitcher } from '@core/i18n/locale-switcher/locale-switcher';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { FieldError } from '@shared/field/field-error';
import { Notice } from '@shared/notice/notice';
import { PasswordInput } from '@shared/password-input/password-input';
import { SetupStore } from '../../state/setup.store';

@Component({
  selector: 'app-setup',
  imports: [
    FormsModule,
    RouterLink,
    MatButton,
    MatCard,
    MatCardContent,
    MatFormField,
    MatLabel,
    MatHint,
    MatError,
    MatInput,
    Notice,
    PasswordInput,
    FieldError,
    LocaleSwitcher,
    TranslatePipe,
    ErrorTextPipe,
  ],
  templateUrl: './setup.html',
  styleUrl: './setup.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SetupPage {
  private readonly setup = inject(SetupStore);
  private readonly auth = inject(AuthStore);
  private readonly locale = inject(LocaleStore);
  private readonly router = inject(Router);

  readonly token = input<string>();

  readonly tokenFromLink = computed(() => (this.token() ?? '') !== '');
  readonly key = linkedSignal(() => this.token() ?? '');
  readonly username = signal('');
  readonly password = signal('');
  readonly confirm = signal('');
  readonly submitted = signal(false);

  readonly busy = this.setup.busy;
  readonly error = this.setup.error;
  readonly done = computed(() => this.error()?.code === 'setup_done');

  readonly keyInvalid = computed(() => this.submitted() && this.key().trim() === '');
  readonly usernameInvalid = computed(() => this.submitted() && this.username().trim() === '');
  readonly passwordInvalid = computed(() => this.submitted() && this.password() === '');
  readonly confirmInvalid = computed(
    () => this.submitted() && !this.passwordInvalid() && this.confirm() !== this.password(),
  );

  readonly tokenError = computed(() => this.message(this.keyInvalid(), 'setup.errors.tokenRequired', 'token'));
  readonly usernameError = computed(() =>
    this.message(this.usernameInvalid(), 'setup.errors.usernameRequired', 'username'),
  );
  readonly passwordError = computed(() =>
    this.message(this.passwordInvalid(), 'setup.errors.passwordRequired', 'password'),
  );

  async submit(): Promise<void> {
    this.submitted.set(true);

    if (this.keyInvalid() || this.usernameInvalid() || this.passwordInvalid() || this.confirmInvalid()) {
      return;
    }

    const created = await this.setup.complete({
      token: this.key().trim(),
      username: this.username().trim(),
      password: this.password(),
    });

    if (created) {
      await this.auth.restore();
      await this.router.navigateByUrl('/');
    }
  }

  private message(missing: boolean, missingKey: string, field: string): string {
    if (missing) {
      return this.locale.translate(missingKey);
    }
    return errorText(this.locale, this.error()?.fields?.[field]?.[0]);
  }
}
