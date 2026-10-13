import { ChangeDetectionStrategy, Component, computed, inject, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButton } from '@angular/material/button';

import { errorText, ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { Notice } from '@shared/notice/notice';
import { PasswordInput } from '@shared/password-input/password-input';
import { AuthStore } from '../../state/auth.store';

@Component({
  selector: 'app-change-password-form',
  imports: [FormsModule, MatButton, Notice, PasswordInput, ErrorTextPipe, TranslatePipe],
  templateUrl: './change-password-form.html',
  styleUrl: './change-password-form.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChangePasswordForm {
  private readonly auth = inject(AuthStore);
  private readonly locale = inject(LocaleStore);

  readonly changed = output();

  readonly current = signal('');
  readonly fresh = signal('');
  readonly confirm = signal('');
  private readonly submitted = signal(false);

  readonly busy = this.auth.busy;
  private readonly failure = computed(() => (this.submitted() ? this.auth.error() : null));

  readonly currentError = computed(() => {
    if (this.submitted() && this.current() === '') {
      return this.locale.translate('password.required');
    }
    return this.failure()?.code === 'invalid_password' ? errorText(this.locale, 'invalid_password') : '';
  });
  readonly freshError = computed(() => {
    if (this.submitted() && this.fresh() === '') {
      return this.locale.translate('auth.changePassword.newRequired');
    }
    return errorText(this.locale, this.failure()?.fields?.['new_password']?.[0]);
  });
  readonly confirmError = computed(() =>
    this.submitted() && this.fresh() !== '' && this.confirm() !== this.fresh()
      ? this.locale.translate('auth.changePassword.mismatch')
      : '',
  );
  readonly otherFailure = computed(() => {
    const failure = this.failure();
    return failure && failure.code !== 'invalid_password' && !failure.fields ? failure : null;
  });

  async submit(): Promise<void> {
    this.auth.clearError();
    this.submitted.set(true);
    if (this.current() === '' || this.fresh() === '' || this.confirm() !== this.fresh() || this.busy()) {
      return;
    }
    const changed = await this.auth.changePassword({
      current_password: this.current(),
      new_password: this.fresh(),
    });
    if (changed) {
      this.current.set('');
      this.fresh.set('');
      this.confirm.set('');
      this.submitted.set(false);
      this.changed.emit();
    }
  }
}
