import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MatButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';

import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { AppDatePipe } from '@shared/app-date/app-date.pipe';
import { Dialogs } from '@shared/dialogs/dialogs';
import { PasswordPrompt } from '@shared/password-prompt/password-prompt';
import type { PasswordPromptData } from '@shared/password-prompt/password-prompt.types';
import { Toaster } from '@shared/toaster/toaster';
import { ChangePasswordForm } from '../../components/change-password-form/change-password-form';
import { RecoveryCodes } from '../../components/recovery-codes/recovery-codes';
import { AuthStore } from '../../state/auth.store';

@Component({
  selector: 'app-account-page',
  imports: [MatButton, MatCard, MatCardContent, ChangePasswordForm, RecoveryCodes, AppDatePipe, TranslatePipe],
  providers: [Dialogs],
  templateUrl: './account.html',
  styleUrl: './account.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AccountPage {
  private readonly auth = inject(AuthStore);
  private readonly dialogs = inject(Dialogs);
  private readonly toaster = inject(Toaster);
  private readonly locale = inject(LocaleStore);

  readonly user = this.auth.user;
  readonly recoveryCodes = this.auth.recoveryCodes;

  changed(): void {
    this.toaster.add({ severity: 'success', summary: this.locale.translate('account.passwordChanged') });
  }

  async newRecoveryCodes(): Promise<void> {
    this.auth.clearError();
    await this.dialogs
      .open<boolean, PasswordPromptData>(PasswordPrompt, {
        titleKey: 'account.recovery.promptTitle',
        size: 'sm',
        data: {
          titleKey: 'account.recovery.promptTitle',
          bodyKey: 'account.recovery.promptBody',
          submitKey: 'account.recovery.promptSubmit',
          submit: (password) => this.auth.newRecoveryCodes(password),
          error: this.auth.error,
        },
      })
      .whenClosed();
  }

  dismissCodes(): void {
    this.auth.dismissRecoveryCodes();
  }
}
