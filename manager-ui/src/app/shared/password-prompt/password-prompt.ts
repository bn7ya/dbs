import { ChangeDetectionStrategy, Component, computed, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonDirective } from 'primeng/button';
import { Message } from 'primeng/message';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { injectDialogData, injectDialogRef } from '../dialogs/dialogs';
import { Field } from '../field/field';
import { PasswordInput } from '../password-input/password-input';
import type { PasswordPromptData } from './password-prompt.types';

@Component({
  selector: 'app-password-prompt',
  imports: [FormsModule, ButtonDirective, Message, PasswordInput, Field, ErrorTextPipe, TranslatePipe],
  templateUrl: './password-prompt.html',
  styleUrl: './password-prompt.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PasswordPrompt {
  protected readonly data = injectDialogData<PasswordPromptData>();
  private readonly ref = injectDialogRef<boolean>();

  readonly password = signal('');
  private readonly submitted = signal(false);
  readonly busy = signal(false);

  readonly missing = computed(() => this.submitted() && this.password() === '');

  private readonly failure = computed(() => (this.submitted() && !this.busy() ? this.data.error() : null));

  readonly rejected = computed(() => this.failure()?.code === 'invalid_password');
  readonly otherFailure = computed(() => {
    const failure = this.failure();
    return failure && failure.code !== 'invalid_password' ? failure : null;
  });

  async submit(): Promise<void> {
    this.submitted.set(true);
    if (this.password() === '' || this.busy()) {
      return;
    }
    this.busy.set(true);
    try {
      if (await this.data.submit(this.password())) {
        this.ref.close(true);
      }
    } finally {
      this.busy.set(false);
    }
  }

  cancel(): void {
    this.ref.close();
  }
}
