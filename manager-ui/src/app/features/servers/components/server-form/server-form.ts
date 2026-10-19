import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButton } from '@angular/material/button';
import { MatError, MatFormField, MatHint, MatLabel } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';
import { MatRadioButton, MatRadioGroup } from '@angular/material/radio';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { injectDialogData, injectDialogRef } from '@shared/dialogs/dialogs';
import { FieldError } from '@shared/field/field-error';
import { Notice } from '@shared/notice/notice';
import { PasswordInput } from '@shared/password-input/password-input';
import type { AuthMethod, Server, ServerUpdate } from '../../data/servers.types';
import { ServersStore } from '../../state/servers.store';
import type { AuthMethodOption, ServerDraft, ServerDraftField, ServerFormData } from './server-form.types';

const AUTH_METHODS: readonly AuthMethodOption[] = [
  { value: 'key', labelKey: 'servers.authMethod.key' },
  { value: 'password', labelKey: 'servers.authMethod.password' },
];

@Component({
  selector: 'app-server-form',
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
    FieldError,
    Notice,
    PasswordInput,
    ErrorTextPipe,
    TranslatePipe,
  ],
  templateUrl: './server-form.html',
  styleUrl: './server-form.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ServerForm {
  private readonly store = inject(ServersStore);
  private readonly ref = injectDialogRef<Server>();

  readonly editing = injectDialogData<ServerFormData>().server;

  protected readonly authMethods = AUTH_METHODS;

  readonly draft = signal<ServerDraft>(draftOf(this.editing));

  readonly saving = this.store.saving;
  private readonly saveError = this.store.saveError;

  private readonly attempted = signal(false);
  private readonly edited = signal<ReadonlySet<ServerDraftField>>(new Set());

  private readonly problems = computed(() => problemsIn(this.draft(), this.editing));

  private readonly shown = computed(() => {
    const shown = new Map<string, string>();
    if (this.attempted()) {
      for (const [field, code] of this.problems()) {
        shown.set(field, code);
      }
    }
    const edited = this.edited();
    for (const [field, codes] of Object.entries(this.saveError()?.fields ?? {})) {
      if (!shown.has(field) && !edited.has(field as ServerDraftField) && codes.length > 0) {
        shown.set(field, codes[0]);
      }
    }
    return shown;
  });

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

  readonly keySaved = this.editing.has_private_key;
  readonly keyPassphraseSaved = this.editing.has_key_passphrase;
  readonly passwordSaved = this.editing.has_password;

  constructor() {
    this.store.resetForm();
  }

  error(field: ServerDraftField): string | null {
    return this.shown().get(field) ?? null;
  }

  update<K extends keyof ServerDraft>(field: K, value: ServerDraft[K]): void {
    this.draft.update((draft) => ({ ...draft, [field]: value }));
    this.edited.update((edited) => new Set(edited).add(field));
  }

  setAuthMethod(method: AuthMethod | null): void {
    if (method) {
      this.update('auth_method', method);
    }
  }

  setAccountPassword(password: string): void {
    this.accountPassword.set(password);
    this.passwordEdited.set(true);
  }

  async save(): Promise<void> {
    this.attempted.set(true);
    if (this.problems().size > 0) {
      return;
    }
    const changes = changesOf(this.editing, this.draft());
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
    const saved = await this.store.update(this.editing.id, { ...changes, ...password });
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

function problemsIn(draft: ServerDraft, editing: Server): ReadonlyMap<ServerDraftField, string> {
  const problems = new Map<ServerDraftField, string>();
  for (const field of ['name', 'host', 'username'] as const) {
    if (draft[field].trim() === '') {
      problems.set(field, 'required');
    }
  }
  const port = draft.port;
  if (port === null || !Number.isInteger(port) || port < 1 || port > 65535) {
    problems.set('port', 'port_range');
  }
  const keyKept = editing.auth_method === 'key' && editing.has_private_key;
  if (draft.auth_method === 'key' && draft.private_key.trim() === '' && !keyKept) {
    problems.set('private_key', 'required');
  }
  const passwordKept = editing.auth_method === 'password' && editing.has_password;
  if (draft.auth_method === 'password' && draft.password === '' && !passwordKept) {
    problems.set('password', 'required');
  }
  return problems;
}

function draftOf(server: Server): ServerDraft {
  return {
    name: server.name,
    host: server.host,
    port: server.port,
    username: server.username,
    auth_method: server.auth_method,
    private_key: '',
    key_passphrase: '',
    password: '',
  };
}

function changesOf(server: Server, draft: ServerDraft): ServerUpdate {
  const name = draft.name.trim();
  const host = draft.host.trim();
  const port = draft.port ?? server.port;
  const username = draft.username.trim();
  const changed = {
    ...(name !== server.name ? { name } : {}),
    ...(host !== server.host ? { host } : {}),
    ...(port !== server.port ? { port } : {}),
    ...(username !== server.username ? { username } : {}),
  };
  const methodChanged = draft.auth_method !== server.auth_method;
  const secrets =
    draft.auth_method === 'key'
      ? {
          ...(draft.private_key.trim() ? { private_key: draft.private_key } : {}),
          ...(draft.key_passphrase ? { key_passphrase: draft.key_passphrase } : {}),
        }
      : { ...(draft.password ? { password: draft.password } : {}) };
  const signIn = methodChanged || Object.keys(secrets).length > 0 ? { auth_method: draft.auth_method, ...secrets } : {};
  return { ...changed, ...signIn };
}
