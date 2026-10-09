import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { ButtonDirective } from 'primeng/button';
import { Card } from 'primeng/card';
import { InputText } from 'primeng/inputtext';
import { Message } from 'primeng/message';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { LocaleSwitcher } from '@core/i18n/locale-switcher/locale-switcher';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { Field } from '@shared/field/field';
import { FieldControl } from '@shared/field/field-control';
import { PasswordInput } from '@shared/password-input/password-input';
import { AuthStore } from '../../state/auth.store';

@Component({
  selector: 'app-sign-in',
  imports: [
    FormsModule,
    ButtonDirective,
    Card,
    InputText,
    Message,
    PasswordInput,
    Field,
    FieldControl,
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
