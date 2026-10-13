import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButton } from '@angular/material/button';
import { MatError, MatFormField, MatHint, MatLabel } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';

import { errorText, ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { injectDialogData, injectDialogRef } from '@shared/dialogs/dialogs';
import { FieldError } from '@shared/field/field-error';
import { isolated } from '@shared/isolated/isolated';
import { Notice } from '@shared/notice/notice';
import { PasswordInput } from '@shared/password-input/password-input';
import { AccountsStore } from '../../state/accounts.store';
import type { AccountDialogData } from '../role-form/role-form.types';

@Component({
  selector: 'app-hand-over-form',
  imports: [
    FormsModule,
    MatButton,
    MatFormField,
    MatLabel,
    MatHint,
    MatError,
    MatInput,
    FieldError,
    Notice,
    PasswordInput,
    ErrorTextPipe,
    TranslatePipe,
  ],
  templateUrl: './hand-over-form.html',
  styleUrl: './hand-over-form.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class HandOverForm {
  private readonly store = inject(AccountsStore);
  private readonly locale = inject(LocaleStore);
  private readonly ref = injectDialogRef<boolean>();

  readonly account = injectDialogData<AccountDialogData>().account;
  readonly name = isolated(this.account.username);

  readonly password = signal('');
  readonly code = signal('');
  private readonly submitted = signal(false);

  readonly busy = this.store.busy;
  private readonly failure = computed(() => (this.submitted() ? this.store.formError() : null));

  readonly passwordError = computed(() => {
    if (this.submitted() && this.password() === '') {
      return this.locale.translate('password.required');
    }
    return this.failure()?.code === 'invalid_password' ? errorText(this.locale, 'invalid_password') : '';
  });
  readonly codeError = computed(() => {
    if (this.submitted() && this.code().trim() === '') {
      return this.locale.translate('auth.twoFactor.codeRequired');
    }
    return this.failure()?.code === 'invalid_code' ? errorText(this.locale, 'invalid_code') : '';
  });
  readonly formFailure = computed(() => {
    const failure = this.failure();
    return failure && failure.code !== 'invalid_password' && failure.code !== 'invalid_code' ? failure : null;
  });

  constructor() {
    this.store.resetForm();
  }

  cancel(): void {
    this.ref.close();
  }

  async submit(): Promise<void> {
    this.store.resetForm();
    this.submitted.set(true);
    if (this.password() === '' || this.code().trim() === '') {
      return;
    }
    if (await this.store.handOver(this.account, { password: this.password(), code: this.code().trim() })) {
      this.ref.close(true);
    }
  }
}
