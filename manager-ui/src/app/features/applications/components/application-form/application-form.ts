import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButton } from '@angular/material/button';
import { MatError, MatFormField, MatHint, MatLabel } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { Dialogs, injectDialogData, injectDialogRef } from '@shared/dialogs/dialogs';
import { FieldError } from '@shared/field/field-error';
import { Notice } from '@shared/notice/notice';
import { PasswordInput } from '@shared/password-input/password-input';
import type { Application } from '../../data/applications.types';
import { ApplicationsStore } from '../../state/applications.store';
import { browseServer } from '../server-browser/browse-server';
import type { BrowsedField } from '../server-browser/server-browser.types';
import { changedSettings, draftOf, draftProblems } from '../settings-fields/application-draft';
import { SettingsFields } from '../settings-fields/settings-fields';
import type { ApplicationDraft, DraftErrors, DraftField } from '../settings-fields/settings-fields.types';
import type { ApplicationFormData } from './application-form.types';

@Component({
  selector: 'app-application-form',
  imports: [
    FormsModule,
    MatButton,
    MatError,
    MatFormField,
    MatHint,
    MatInput,
    MatLabel,
    FieldError,
    Notice,
    PasswordInput,
    SettingsFields,
    ErrorTextPipe,
    TranslatePipe,
  ],
  templateUrl: './application-form.html',
  styleUrl: './application-form.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ApplicationForm {
  private readonly store = inject(ApplicationsStore);
  private readonly ref = injectDialogRef<Application>();
  private readonly dialogs = inject(Dialogs);

  readonly editing = injectDialogData<ApplicationFormData>().application;

  readonly draft = signal<ApplicationDraft>(draftOf(this.editing));
  private readonly attempted = signal(false);
  private readonly edited = signal<ReadonlySet<DraftField>>(new Set());

  readonly saving = this.store.saving;
  private readonly saveError = this.store.saveError;

  readonly accountPassword = signal('');
  private readonly passwordEdited = signal(false);

  readonly passwordAsked = computed(() => (this.saveError()?.fields?.['account_password'] ?? []).length > 0);
  readonly passwordShown = signal(false);
  readonly passwordMissing = computed(() => this.passwordAsked() && !this.passwordEdited() && this.accountPassword() === '');
  readonly passwordRejected = computed(() => this.saveError()?.code === 'invalid_password' && !this.passwordEdited());

  readonly formFailure = computed(() => {
    const failure = this.saveError();
    return failure && failure.code !== 'invalid_password' && !failure.fields ? failure : null;
  });

  private readonly problems = computed(() => draftProblems(this.draft()));

  readonly errors = computed<DraftErrors>(() => {
    const shown: Partial<Record<DraftField, string>> = {};
    if (this.attempted()) {
      for (const [field, code] of this.problems()) {
        shown[field] = code;
      }
    }
    const edited = this.edited();
    for (const [field, codes] of Object.entries(this.saveError()?.fields ?? {})) {
      const name = field as DraftField;
      if (field !== 'account_password' && shown[name] === undefined && !edited.has(name) && codes.length > 0) {
        shown[name] = codes[0];
      }
    }
    return shown;
  });

  constructor() {
    this.store.resetForm();
  }

  update<K extends keyof ApplicationDraft>(field: K, value: ApplicationDraft[K]): void {
    this.changeDraft({ [field]: value });
  }

  changeDraft(change: Partial<ApplicationDraft>): void {
    this.draft.update((draft) => ({ ...draft, ...change }));
    this.edited.update((edited) => new Set([...edited, ...(Object.keys(change) as DraftField[])]));
  }

  setAccountPassword(password: string): void {
    this.accountPassword.set(password);
    this.passwordEdited.set(true);
  }

  async browse(field: BrowsedField): Promise<void> {
    const picked = await browseServer(this.dialogs, this.editing.server.id, field, this.draft());
    if (!picked) {
      return;
    }
    if (field === 'file_roots') {
      const roots = this.draft().file_roots;
      if (!roots.includes(picked)) {
        this.update('file_roots', [...roots, picked]);
      }
    } else if (field !== 'folder') {
      this.update(field, picked);
    }
  }

  async save(): Promise<void> {
    this.attempted.set(true);
    if (this.problems().size > 0) {
      return;
    }
    const changes = changedSettings(draftOf(this.editing), this.draft());
    if (Object.keys(changes).length === 0) {
      this.ref.close();
      return;
    }
    if (this.passwordShown() && this.accountPassword() === '') {
      return;
    }
    this.edited.set(new Set());
    this.passwordEdited.set(false);
    const password = this.accountPassword() ? { account_password: this.accountPassword() } : {};
    const saved = await this.store.update({ ...changes, ...password });
    if (saved) {
      this.ref.close(saved);
    } else if (this.passwordAsked()) {
      this.passwordShown.set(true);
    }
  }

  close(): void {
    this.ref.close();
  }
}
