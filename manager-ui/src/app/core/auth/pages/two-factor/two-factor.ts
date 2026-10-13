import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { MatError, MatFormField, MatHint, MatLabel } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';
import { ActivatedRoute, Router } from '@angular/router';

import { errorText, ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { LocaleSwitcher } from '@core/i18n/locale-switcher/locale-switcher';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { FieldError } from '@shared/field/field-error';
import { Notice } from '@shared/notice/notice';
import { AuthStore } from '../../state/auth.store';

@Component({
  selector: 'app-two-factor',
  imports: [
    FormsModule,
    MatButton,
    MatCard,
    MatCardContent,
    MatFormField,
    MatLabel,
    MatHint,
    MatError,
    MatInput,
    Notice,
    FieldError,
    LocaleSwitcher,
    TranslatePipe,
    ErrorTextPipe,
  ],
  templateUrl: './two-factor.html',
  styleUrl: './two-factor.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TwoFactorPage {
  private readonly auth = inject(AuthStore);
  private readonly locale = inject(LocaleStore);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  readonly recovery = signal(false);
  readonly code = signal('');
  private readonly submitted = signal(false);

  readonly busy = this.auth.busy;
  private readonly failure = computed(() => (this.submitted() ? this.auth.error() : null));
  readonly expired = computed(() => this.failure()?.code === 'sign_in_expired');
  readonly otherFailure = computed(() => {
    const failure = this.failure();
    return failure && failure.code !== 'invalid_code' ? failure : null;
  });
  readonly codeError = computed(() => {
    if (this.submitted() && this.code().trim() === '') {
      return this.locale.translate(this.recovery() ? 'auth.twoFactor.recoveryRequired' : 'auth.twoFactor.codeRequired');
    }
    return this.failure()?.code === 'invalid_code' ? errorText(this.locale, 'invalid_code') : '';
  });

  switchFactor(): void {
    this.recovery.update((recovery) => !recovery);
    this.code.set('');
    this.submitted.set(false);
    this.auth.clearError();
  }

  async submit(): Promise<void> {
    this.auth.clearError();
    this.submitted.set(true);
    const typed = this.code().trim();
    if (typed === '' || this.busy()) {
      return;
    }
    const factor = this.recovery() ? { recovery_code: typed } : { code: typed };
    if (await this.auth.secondFactor(factor)) {
      await this.router.navigateByUrl(this.route.snapshot.queryParamMap.get('next') ?? '/');
    }
  }

  async startOver(): Promise<void> {
    const next = this.route.snapshot.queryParamMap.get('next');
    await this.router.navigate(['/sign-in'], next ? { queryParams: { next } } : {});
  }
}
