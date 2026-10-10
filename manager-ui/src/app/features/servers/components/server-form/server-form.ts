import { ChangeDetectionStrategy, Component, afterRenderEffect, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { COMMA, ENTER } from '@angular/cdk/keycodes';
import { MatButton, MatIconButton } from '@angular/material/button';
import { MatChipGrid, MatChipInput, MatChipRemove, MatChipRow, type MatChipInputEvent } from '@angular/material/chips';
import { MatError, MatFormField, MatHint, MatLabel, MatSuffix } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';
import { MatRadioButton, MatRadioGroup } from '@angular/material/radio';
import { MatStep, MatStepper, MatStepperIcon } from '@angular/material/stepper';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { Dialogs, injectDialogData, injectDialogRef } from '@shared/dialogs/dialogs';
import { FieldError } from '@shared/field/field-error';
import { Notice } from '@shared/notice/notice';
import { PasswordInput } from '@shared/password-input/password-input';
import type { AuthMethod, Server, ServerSettings } from '../../data/servers.types';
import { browseServer } from '../server-browser/browse-server';
import type { BrowsedField } from '../server-browser/server-browser.types';
import { ServersStore } from '../../state/servers.store';
import type {
  AuthMethodOption,
  ServerDraft,
  ServerDraftField,
  ServerFormData,
  ServerFormStep,
} from './server-form.types';

const BLANK: ServerDraft = {
  name: '',
  host: '',
  port: 22,
  username: '',
  auth_method: 'key',
  private_key: '',
  key_passphrase: '',
  password: '',
  project_dir: '',
  python_path: 'python3',
  manage_path: 'manage.py',
  settings_module: '',
  remote_backup_dir: '/var/backups/dbs',
  file_roots: [],
  env_path: '',
};

const FIELD_STEPS: Readonly<Record<ServerDraftField, ServerFormStep>> = {
  name: 'connection',
  host: 'connection',
  port: 'connection',
  username: 'connection',
  auth_method: 'connection',
  private_key: 'connection',
  key_passphrase: 'connection',
  password: 'connection',
  project_dir: 'project',
  python_path: 'project',
  manage_path: 'project',
  settings_module: 'project',
  remote_backup_dir: 'project',
  file_roots: 'project',
  env_path: 'project',
};

const STEP_LABELS: Readonly<Record<ServerFormStep, string>> = {
  connection: 'servers.form.steps.connection',
  project: 'servers.form.steps.project',
};

@Component({
  selector: 'app-server-form',
  imports: [
    FormsModule,
    MatButton,
    MatIconButton,
    MatChipGrid,
    MatChipRow,
    MatChipRemove,
    MatChipInput,
    MatFormField,
    MatLabel,
    MatHint,
    MatError,
    MatInput,
    MatRadioGroup,
    MatRadioButton,
    MatStepper,
    MatStep,
    MatStepperIcon,
    MatSuffix,
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
  private readonly dialogs = inject(Dialogs);

  readonly editing = injectDialogData<ServerFormData>().server;

  protected readonly authMethods: readonly AuthMethodOption[] = [
    { value: 'key', labelKey: 'servers.authMethod.key' },
    { value: 'password', labelKey: 'servers.authMethod.password' },
  ];
  protected readonly separators = [ENTER, COMMA];

  readonly steps: readonly ServerFormStep[] = ['connection', 'project'];
  readonly stepLabels = STEP_LABELS;

  readonly step = signal(0);
  protected readonly shownStep = signal(0);
  readonly onLastStep = computed(() => this.step() === this.steps.length - 1);

  readonly draft = signal<ServerDraft>(draftOf(this.editing));


  readonly saving = this.store.saving;
  readonly saveError = this.store.saveError;

  private readonly attempted = signal<ReadonlySet<ServerFormStep>>(new Set());

  private readonly edited = signal<ReadonlySet<ServerDraftField>>(new Set());

  private readonly problems = computed(() =>
    problemsIn(this.draft(), this.editing),
  );

  private readonly shown = computed(() => {
    const shown = new Map<string, string>();
    const attempted = this.attempted();
    for (const [field, code] of this.problems()) {
      if (attempted.has(FIELD_STEPS[field])) {
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

  readonly needsPassword = computed(
    () => changesMoreThanName(settingsOf(draftOf(this.editing)), settingsOf(this.draft())),
  );

  private readonly passwordAsked = computed(() => (this.saveError()?.fields?.['account_password'] ?? []).length > 0);

  readonly passwordShown = computed(() => this.needsPassword() || this.passwordAsked());

  readonly passwordMissing = computed(
    () =>
      this.accountPassword() === '' &&
      ((this.attempted().has('project') && this.needsPassword()) || (this.passwordAsked() && !this.passwordEdited())),
  );

  readonly passwordRejected = computed(() => this.saveError()?.code === 'invalid_password' && !this.passwordEdited());
  readonly formFailure = computed(() => {
    const failure = this.saveError();
    return failure && failure.code !== 'invalid_password' ? failure : null;
  });

  readonly keySaved = computed(() => this.editing.has_private_key);
  readonly keyPassphraseSaved = computed(() => this.editing.has_key_passphrase);
  readonly passwordSaved = computed(() => this.editing.has_password);

  constructor() {
    this.store.resetForm();
    afterRenderEffect({ write: () => this.shownStep.set(this.step()) });
  }

  error(field: ServerDraftField): string | null {
    return this.shown().get(field) ?? null;
  }

  stepDone(step: ServerFormStep): boolean {
    return this.attempted().has(step) && this.stepReady(step);
  }

  stepReady(step: ServerFormStep): boolean {
    for (const field of this.problems().keys()) {
      if (FIELD_STEPS[field] === step) {
        return false;
      }
    }
    return true;
  }

  update<K extends keyof ServerDraft>(field: K, value: ServerDraft[K]): void {
    this.draft.update((draft) => ({ ...draft, [field]: value }));
    this.edited.update((edited) => new Set(edited).add(field));
  }

  async browse(field: BrowsedField): Promise<void> {
    const chosen = await browseServer(this.dialogs, this.editing.id, field, this.draft());
    if (!chosen) {
      return;
    }
    if (field === 'file_roots') {
      const roots = this.draft().file_roots;
      if (!roots.includes(chosen)) {
        this.update('file_roots', [...roots, chosen]);
      }
    } else {
      this.update(field, chosen);
    }
  }

  setAccountPassword(password: string): void {
    this.accountPassword.set(password);
    this.passwordEdited.set(true);
  }

  setAuthMethod(method: AuthMethod | null): void {
    if (method) {
      this.update('auth_method', method);
    }
  }

  addFileRoot(event: MatChipInputEvent): void {
    const root = event.value.trim();
    if (root !== '') {
      this.update('file_roots', [...this.draft().file_roots, root]);
    }
    event.chipInput.clear();
  }

  removeFileRoot(index: number): void {
    this.update(
      'file_roots',
      this.draft().file_roots.filter((_, position) => position !== index),
    );
  }


  back(): void {
    this.step.update((step) => Math.max(0, step - 1));
  }

  async advance(): Promise<void> {
    if (this.onLastStep()) {
      await this.save();
      return;
    }
    const step = this.steps[this.step()];
    this.attempted.update((attempted) => new Set(attempted).add(step));
    if (this.stepReady(step)) {
      this.step.update((index) => index + 1);
    }
  }

  close(): void {
    this.ref.close();
  }

  private async save(): Promise<void> {
    this.attempted.set(new Set(this.steps));
    const unready = this.steps.find((step) => !this.stepReady(step));
    if (unready) {
      this.step.set(this.steps.indexOf(unready));
      return;
    }

    if (this.needsPassword() && this.accountPassword() === '') {
      return;
    }

    this.edited.set(new Set());
    this.passwordEdited.set(false);
    const draft = this.draft();
    const password = this.passwordShown() && this.accountPassword() ? { account_password: this.accountPassword() } : {};
    const saved = await this.store.update(this.editing.id, { ...settingsOf(draft), ...password });

    if (saved) {
      this.ref.close(saved);
      return;
    }

    const failedStep = this.steps.find((step) =>
      Object.keys(this.saveError()?.fields ?? {}).some(
        (field) => FIELD_STEPS[field as ServerDraftField] === step,
      ),
    );
    if (failedStep) {
      this.step.set(this.steps.indexOf(failedStep));
    }
  }
}

const ABSOLUTE_PATH = /^\//;

function problemsIn(
  draft: ServerDraft,
  editing: Server,
): ReadonlyMap<ServerDraftField, string> {
  const problems = new Map<ServerDraftField, string>();
  for (const field of ['name', 'host', 'username', 'remote_backup_dir'] as const) {
    if (draft[field].trim() === '') {
      problems.set(field, 'required');
    }
  }
  const port = draft.port;
  if (port === null || !Number.isInteger(port) || port < 1 || port > 65535) {
    problems.set('port', 'port_range');
  }
  if (draft.auth_method === 'key' && draft.private_key.trim() === '' && !editing.has_private_key) {
    problems.set('private_key', 'required');
  }
  if (draft.auth_method === 'password' && draft.password === '' && !editing.has_password) {
    problems.set('password', 'required');
  }
  for (const field of ['project_dir', 'remote_backup_dir', 'env_path'] as const) {
    const path = draft[field].trim();
    if (path !== '' && !ABSOLUTE_PATH.test(path)) {
      problems.set(field, 'absolute_path_required');
    }
  }
  if (draft.file_roots.some((root) => !ABSOLUTE_PATH.test(root.trim()))) {
    problems.set('file_roots', 'absolute_path_required');
  }
  return problems;
}

function draftOf(server: Server): ServerDraft {
  return {
    ...BLANK,
    name: server.name,
    host: server.host,
    port: server.port,
    username: server.username,
    auth_method: server.auth_method,
    project_dir: server.project_dir,
    python_path: server.python_path,
    manage_path: server.manage_path,
    settings_module: server.settings_module,
    remote_backup_dir: server.remote_backup_dir,
    file_roots: server.file_roots,
    env_path: server.env_path,
  };
}

function settingsOf(draft: ServerDraft): ServerSettings {
  const secrets =
    draft.auth_method === 'key'
      ? {
          ...(draft.private_key.trim() ? { private_key: draft.private_key } : {}),
          ...(draft.key_passphrase ? { key_passphrase: draft.key_passphrase } : {}),
        }
      : { ...(draft.password ? { password: draft.password } : {}) };
  return {
    name: draft.name.trim(),
    host: draft.host.trim(),
    port: draft.port ?? 22,
    username: draft.username.trim(),
    auth_method: draft.auth_method,
    ...secrets,
    project_dir: draft.project_dir.trim(),
    python_path: draft.python_path.trim(),
    manage_path: draft.manage_path.trim(),
    settings_module: draft.settings_module.trim(),
    remote_backup_dir: draft.remote_backup_dir.trim(),
    file_roots: draft.file_roots.map((root) => root.trim()),
    env_path: draft.env_path.trim(),
  };
}

function changesMoreThanName(before: ServerSettings, after: ServerSettings): boolean {
  const fields = new Set([...Object.keys(before), ...Object.keys(after)] as (keyof ServerSettings)[]);
  fields.delete('name');
  return [...fields].some((field) => JSON.stringify(before[field]) !== JSON.stringify(after[field]));
}
