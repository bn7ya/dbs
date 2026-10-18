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
import { Can } from '@core/auth/directives/can';
import { injectDialogData, injectDialogRef } from '@shared/dialogs/dialogs';
import { FieldError } from '@shared/field/field-error';
import { isolated } from '@shared/isolated/isolated';
import { Notice } from '@shared/notice/notice';
import { PasswordInput } from '@shared/password-input/password-input';
import { uniqueId } from '@shared/unique-id';
import type { ApplicationChoice, RestoreMode, RestoreRequest } from '../../data/backups.types';
import { BackupsStore } from '../../state/backups.store';
import type { RestoreFormData, Sending } from './restore-form.types';

const MODES: readonly RestoreMode[] = ['merge', 'replace'];

const FORM_FIELDS = ['account_password', 'application_name', 'target_application'];

@Component({
  selector: 'app-restore-form',
  imports: [
    Can,
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
  readonly applicationName = signal('');
  readonly targetApplication = signal<string | null>(null);

  readonly targets = computed(() => this.store.applications().filter((each) => each.id !== this.file.application));

  readonly restoreOnto = computed(
    () => this.targets().find((each) => each.id === this.targetApplication())?.name ?? this.file.application_name,
  );

  readonly ontoHint = computed(() =>
    this.locale.translate('backups.restore.applicationNameHint', { name: isolated(this.restoreOnto()) }),
  );

  readonly sending = signal<Sending | null>(null);

  private readonly sendError = this.store.restoreError;

  private readonly attempted = signal(false);

  private readonly passwordEdited = signal(false);
  private readonly nameEdited = signal(false);

  // Spaces around it aside, as the backend compares it.
  private readonly nameMatches = computed(() => this.applicationName().trim() === this.restoreOnto());

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
    return this.nameEdited() ? null : (this.sendError()?.fields?.['application_name']?.[0] ?? null);
  });

  readonly nameErrorText = computed(() => {
    const code = this.nameError();
    return code === null ? '' : errorText(this.locale, code);
  });

  readonly targetError = computed(() => {
    const code = this.sendError()?.fields?.['target_application']?.[0];
    return code === undefined ? '' : errorText(this.locale, code);
  });

  readonly formFailure = computed(() => {
    const failure = this.sendError();
    const fields = Object.keys(failure?.fields ?? {});
    const aboutAField = fields.some((field) => FORM_FIELDS.includes(field));
    return failure && failure.code !== 'invalid_password' && !aboutAField ? failure : null;
  });

  constructor() {
    this.store.resetRestoreForm();
  }

  targetLabel(target: ApplicationChoice): string {
    return this.locale.translate('backups.applicationOnServer', {
      name: isolated(target.name),
      server: isolated(target.server.name),
    });
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

  setApplicationName(name: string): void {
    this.applicationName.set(name);
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
    const target = this.targetApplication();
    const onto = target === null ? {} : { target_application: target };
    const request: RestoreRequest =
      sending === 'rehearse'
        ? { mode: this.mode(), rehearse: true, ...onto }
        : {
            mode: this.mode(),
            rehearse: false,
            account_password: this.accountPassword(),
            application_name: this.applicationName().trim(),
            ...onto,
          };
    const started = await this.store.restore(this.file, request);
    this.sending.set(null);
    if (started) {
      this.ref.close(true);
    }
  }
}
