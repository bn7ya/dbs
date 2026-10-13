import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButton } from '@angular/material/button';
import { MatError, MatFormField, MatHint, MatLabel } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';

import { errorText, ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { injectDialogRef } from '@shared/dialogs/dialogs';
import { FieldError } from '@shared/field/field-error';
import { Notice } from '@shared/notice/notice';
import { PasswordInput } from '@shared/password-input/password-input';
import type { AssignableRole } from '../../data/accounts.types';
import { AccountsStore } from '../../state/accounts.store';
import { RoleChoice } from '../role-choice/role-choice';

@Component({
  selector: 'app-account-form',
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
    RoleChoice,
    ErrorTextPipe,
    TranslatePipe,
  ],
  templateUrl: './account-form.html',
  styleUrl: './account-form.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AccountForm {
  private readonly store = inject(AccountsStore);
  private readonly locale = inject(LocaleStore);
  private readonly ref = injectDialogRef<boolean>();

  readonly username = signal('');
  readonly role = signal<AssignableRole>('operator');
  readonly password = signal('');
  readonly confirm = signal('');
  private readonly submitted = signal(false);

  readonly busy = this.store.busy;
  private readonly failure = computed(() => (this.submitted() ? this.store.formError() : null));

  readonly usernameError = computed(() => {
    if (this.submitted() && this.username().trim() === '') {
      return this.locale.translate('accounts.form.usernameRequired');
    }
    return errorText(this.locale, this.failure()?.fields?.['username']?.[0]);
  });
  readonly passwordError = computed(() => {
    if (this.submitted() && this.password() === '') {
      return this.locale.translate('accounts.form.passwordRequired');
    }
    return errorText(this.locale, this.failure()?.fields?.['password']?.[0]);
  });
  readonly confirmError = computed(() =>
    this.submitted() && this.password() !== '' && this.confirm() !== this.password()
      ? this.locale.translate('accounts.form.mismatch')
      : '',
  );
  readonly formFailure = computed(() => {
    const failure = this.failure();
    const fields = failure?.fields ?? {};
    return failure && !('username' in fields) && !('password' in fields) ? failure : null;
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
    if (this.username().trim() === '' || this.password() === '' || this.confirm() !== this.password()) {
      return;
    }
    const created = await this.store.create({
      username: this.username().trim(),
      password: this.password(),
      role: this.role(),
    });
    if (created) {
      this.ref.close(true);
    }
  }
}
