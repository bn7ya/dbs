import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButton } from '@angular/material/button';
import { MatError, MatFormField, MatHint, MatLabel } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';
import { MatOption } from '@angular/material/core';
import { MatRadioButton, MatRadioGroup } from '@angular/material/radio';
import { MatSelect } from '@angular/material/select';

import { ErrorTextPipe, errorText } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { injectDialogData, injectDialogRef } from '@shared/dialogs/dialogs';
import { FieldError } from '@shared/field/field-error';
import { Notice } from '@shared/notice/notice';
import { PasswordInput } from '@shared/password-input/password-input';
import { uniqueId } from '@shared/unique-id';
import type { RestoreMode, RestoreRequest } from '../../data/backups.types';
import { BackupsStore } from '../../state/backups.store';
import type { RestoreFormData, Sending } from './restore-form.types';

const MODES: readonly RestoreMode[] = ['merge', 'replace'];

@Component({
  selector: 'app-restore-form',
  imports: [
    FormsModule,
    MatButton,
    MatFormField,
    MatLabel,
    MatHint,
    MatError,
    MatInput,
    MatRadioGroup,
    MatRadioButton,
    MatSelect,
    MatOption,
    FieldError,
    Notice,
    PasswordInput,
    ErrorTextPipe,
    TranslatePipe,
  ],
  templateUrl: './restore-form.html',
  styleUrl: './restore-form.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RestoreForm {
  private readonly store = inject(BackupsStore);
  private readonly locale = inject(LocaleStore);
  private readonly ref = injectDialogRef<boolean>();

  readonly file = injectDialogData<RestoreFormData>().file;

  readonly modeId = uniqueId('restore-mode');
  readonly modes = MODES;

  readonly mode = signal<RestoreMode>('merge');
  readonly accountPassword = signal('');
  readonly serverName = signal('');
  readonly targetServer = signal<string | null>(null);

  readonly targetServers = this.store.targetServers;

  readonly restoreOnto = computed(
    () => this.targetServers().find((each) => each.id === this.targetServer())?.name ?? this.file.server_name,
  );

  readonly sending = signal<Sending | null>(null);

  private readonly sendError = this.store.restoreError;

  private readonly attempted = signal(false);

  private readonly passwordEdited = signal(false);
  private readonly nameEdited = signal(false);

  // Spaces around it aside, as the backend compares it.
  private readonly nameMatches = computed(() => this.serverName().trim() === this.restoreOnto());

  readonly passwordMissing = computed(() => {
    const asked = (this.sendError()?.fields?.['account_password'] ?? []).length > 0 && !this.passwordEdited();
    return this.accountPassword() === '' && (this.attempted() || asked);
  });

  readonly passwordRejected = computed(
    () => this.sendError()?.code === 'invalid_password' && !this.passwordEdited(),
  );

  readonly passwordError = computed(() => {
    if (this.passwordMissing()) {
      return this.locale.translate('password.required');
    }
    return this.passwordRejected() ? errorText(this.locale, 'invalid_password') : '';
  });

  readonly nameError = computed(() => {
    if (this.attempted() && !this.nameMatches()) {
      return 'name_mismatch';
    }
    return this.nameEdited() ? null : (this.sendError()?.fields?.['server_name']?.[0] ?? null);
  });

  readonly nameErrorText = computed(() => {
    const code = this.nameError();
    return code === null ? '' : errorText(this.locale, code);
  });

  readonly targetError = computed(() => {
    const code = this.sendError()?.fields?.['target_server']?.[0];
    return code === undefined ? '' : errorText(this.locale, code);
  });

  readonly formFailure = computed(() => {
    const failure = this.sendError();
    const fields = failure?.fields ?? {};
    const aboutAField = 'account_password' in fields || 'server_name' in fields || 'target_server' in fields;
    return failure && failure.code !== 'invalid_password' && !aboutAField ? failure : null;
  });

  constructor() {
    this.store.resetRestoreForm();
  }

  setMode(mode: RestoreMode | null): void {
    if (mode) {
      this.mode.set(mode);
    }
  }

  setAccountPassword(password: string): void {
    this.accountPassword.set(password);
    this.passwordEdited.set(true);
  }

  setServerName(name: string): void {
    this.serverName.set(name);
    this.nameEdited.set(true);
  }

  cancel(): void {
    this.ref.close();
  }

  async rehearse(): Promise<void> {
    await this.send('rehearse');
  }

  async restore(): Promise<void> {
    this.attempted.set(true);
    if (this.accountPassword() === '' || !this.nameMatches()) {
      return;
    }
    await this.send('restore');
  }

  private async send(sending: Sending): Promise<void> {
    if (this.sending() !== null) {
      return;
    }
    this.sending.set(sending);
    this.passwordEdited.set(false);
    this.nameEdited.set(false);
    const target = this.targetServer();
    const onto = target === null ? {} : { target_server: target };
    const request: RestoreRequest =
      sending === 'rehearse'
        ? { mode: this.mode(), rehearse: true, ...onto }
        : {
            mode: this.mode(),
            rehearse: false,
            account_password: this.accountPassword(),
            server_name: this.serverName().trim(),
            ...onto,
          };
    const started = await this.store.restore(this.file, request);
    this.sending.set(null);
    if (started) {
      this.ref.close(true);
    }
  }
}
