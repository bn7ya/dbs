import { ChangeDetectionStrategy, Component, computed, inject, input, linkedSignal, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { ButtonDirective } from 'primeng/button';
import { Card } from 'primeng/card';
import { InputText } from 'primeng/inputtext';
import { Message } from 'primeng/message';

import { AuthStore } from '@core/auth/state/auth.store';
import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { LocaleSwitcher } from '@core/i18n/locale-switcher/locale-switcher';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { Field } from '@shared/field/field';
import { FieldControl } from '@shared/field/field-control';
import { PasswordInput } from '@shared/password-input/password-input';
import { SetupStore } from '../../state/setup.store';

@Component({
  selector: 'app-setup',
  imports: [
    FormsModule,
    RouterLink,
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
  templateUrl: './setup.html',
  styleUrl: './setup.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SetupPage {
  private readonly setup = inject(SetupStore);
  private readonly auth = inject(AuthStore);
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

  fieldCode(name: string): string | null {
    return this.error()?.fields?.[name]?.[0] ?? null;
  }

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
}
