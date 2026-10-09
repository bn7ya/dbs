import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { MatError, MatFormField, MatLabel } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';
import { ActivatedRoute, Router } from '@angular/router';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { LocaleSwitcher } from '@core/i18n/locale-switcher/locale-switcher';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { FieldError } from '@shared/field/field-error';
import { Notice } from '@shared/notice/notice';
import { PasswordInput } from '@shared/password-input/password-input';
import { AuthStore } from '../../state/auth.store';

@Component({
  selector: 'app-sign-in',
  imports: [
    FormsModule,
    MatButton,
    MatCard,
    MatCardContent,
    MatFormField,
    MatLabel,
    MatError,
    MatInput,
    Notice,
    PasswordInput,
    FieldError,
    LocaleSwitcher,
    TranslatePipe,
    ErrorTextPipe,
  ],
  templateUrl: './sign-in.html',
  styleUrl: './sign-in.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SignInPage {
  private readonly auth = inject(AuthStore);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  readonly username = signal('');
  readonly password = signal('');
  readonly submitted = signal(false);

  readonly busy = this.auth.busy;
  readonly error = this.auth.error;

  readonly usernameInvalid = computed(() => this.submitted() && this.username().trim() === '');
  readonly passwordInvalid = computed(() => this.submitted() && this.password() === '');

  async submit(): Promise<void> {
    this.submitted.set(true);

    if (this.usernameInvalid() || this.passwordInvalid()) {
      return;
    }

    const signedIn = await this.auth.signIn({
      username: this.username().trim(),
      password: this.password(),
    });

    if (signedIn) {
      const next = this.route.snapshot.queryParamMap.get('next') ?? '/';
      await this.router.navigateByUrl(next);
    }
  }
}
