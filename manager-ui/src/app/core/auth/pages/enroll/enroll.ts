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
import { CopyButton } from '@shared/copy-button/copy-button';
import { FieldError } from '@shared/field/field-error';
import { Notice } from '@shared/notice/notice';
import { Skeleton } from '@shared/skeleton/skeleton';
import { QrCode } from '../../components/qr-code/qr-code';
import { RecoveryCodes } from '../../components/recovery-codes/recovery-codes';
import { AuthStore } from '../../state/auth.store';

const SECRET_GROUP = /.{1,4}/g;

@Component({
  selector: 'app-enroll',
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
    Skeleton,
    FieldError,
    CopyButton,
    QrCode,
    RecoveryCodes,
    LocaleSwitcher,
    TranslatePipe,
    ErrorTextPipe,
  ],
  templateUrl: './enroll.html',
  styleUrl: './enroll.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EnrollPage {
  private readonly auth = inject(AuthStore);
  private readonly locale = inject(LocaleStore);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  readonly enrollment = this.auth.enrollment;
  readonly recoveryCodes = this.auth.recoveryCodes;
  readonly busy = this.auth.busy;

  readonly code = signal('');
  private readonly submitted = signal(false);

  readonly groupedSecret = computed(() => this.enrollment()?.secret.match(SECRET_GROUP)?.join(' ') ?? '');
  readonly expired = computed(() => this.auth.error()?.code === 'sign_in_expired');
  private readonly failure = computed(() => (this.submitted() ? this.auth.error() : null));
  readonly loadFailure = computed(() => {
    const failure = this.auth.error();
    return !this.submitted() && failure && !this.expired() ? failure : null;
  });
  readonly otherFailure = computed(() => {
    const failure = this.failure();
    return failure && failure.code !== 'invalid_code' && !this.expired() ? failure : null;
  });
  readonly codeError = computed(() => {
    if (this.submitted() && this.code().trim() === '') {
      return this.locale.translate('auth.twoFactor.codeRequired');
    }
    return this.failure()?.code === 'invalid_code' ? errorText(this.locale, 'invalid_code') : '';
  });

  constructor() {
    if (this.recoveryCodes() === null && this.enrollment() === null) {
      void this.auth.startEnrollment();
    }
  }

  async submit(): Promise<void> {
    this.auth.clearError();
    this.submitted.set(true);
    const typed = this.code().trim();
    if (typed === '' || this.busy()) {
      return;
    }
    await this.auth.enroll(typed);
  }

  async continue(): Promise<void> {
    this.auth.dismissRecoveryCodes();
    await this.router.navigateByUrl(this.route.snapshot.queryParamMap.get('next') ?? '/');
  }

  async startOver(): Promise<void> {
    await this.router.navigate(['/sign-in']);
  }
}
