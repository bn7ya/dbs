import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MatButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { Router } from '@angular/router';

import { LocaleSwitcher } from '@core/i18n/locale-switcher/locale-switcher';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { AppDatePipe } from '@shared/app-date/app-date.pipe';
import { ChangePasswordForm } from '../../components/change-password-form/change-password-form';
import { AuthStore } from '../../state/auth.store';

@Component({
  selector: 'app-password',
  imports: [MatButton, MatCard, MatCardContent, ChangePasswordForm, LocaleSwitcher, AppDatePipe, TranslatePipe],
  templateUrl: './password.html',
  styleUrl: './password.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PasswordPage {
  private readonly auth = inject(AuthStore);
  private readonly router = inject(Router);

  readonly user = this.auth.user;
  readonly signingOut = this.auth.busy;

  async changed(): Promise<void> {
    await this.router.navigateByUrl('/');
  }

  signOut(): void {
    void this.auth.signOut();
  }
}
