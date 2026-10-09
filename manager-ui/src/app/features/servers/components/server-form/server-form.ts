import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonDirective } from 'primeng/button';
import { Checkbox } from 'primeng/checkbox';
import { InputNumber } from 'primeng/inputnumber';
import { InputTags } from 'primeng/inputtags';
import { InputText } from 'primeng/inputtext';
import { Message } from 'primeng/message';
import { RadioButton } from 'primeng/radiobutton';
import { Step, StepList, StepPanel, StepPanels, Stepper } from 'primeng/stepper';
import { Textarea } from 'primeng/textarea';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { injectDialogData, injectDialogRef } from '@shared/dialogs/dialogs';
import { Field } from '@shared/field/field';
import { PasswordInput } from '@shared/password-input/password-input';
import { FieldControl } from '@shared/field/field-control';
import { uniqueId } from '@shared/unique-id';
import type { AuthMethod, HostKey, Server, ServerCreate, ServerSettings } from '../../data/servers.types';
import { ServersStore } from '../../state/servers.store';
import { HostKeyFacts } from '../host-key-facts/host-key-facts';
import type {
  AuthMethodOption,
  ServerDraft,
  ServerDraftField,
  ServerFormData,
  ServerFormStep,
} from './server-form.types';

const NEW_SERVER: ServerDraft = {
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
  remote_backup_dir: '/var/backups/dbs-interface',
  file_roots: [],
  env_path: '',
  backup_passphrase: '',
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
  host_key: 'hostKey',
  project_dir: 'project',
  python_path: 'project',
  manage_path: 'project',
  settings_module: 'project',
  remote_backup_dir: 'project',
  file_roots: 'project',
  env_path: 'project',
  backup_passphrase: 'project',
};

const STEP_LABELS: Readonly<Record<ServerFormStep, string>> = {
  connection: 'servers.form.steps.connection',
  hostKey: 'servers.form.steps.hostKey',
  project: 'servers.form.steps.project',
};

@Component({
  selector: 'app-server-form',
  imports: [
    FormsModule,
    ButtonDirective,
    Checkbox,
    InputNumber,
    InputTags,
    InputText,
    Message,
    RadioButton,
    Stepper,
    StepList,
    Step,
    StepPanels,
    StepPanel,
    Textarea,
    Field,
    PasswordInput,
    FieldControl,
    HostKeyFacts,
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

  protected readonly confirmId = uniqueId('host-key-confirmed');
  protected readonly authMethods: readonly AuthMethodOption[] = [
    { value: 'key', labelKey: 'servers.authMethod.key', inputId: uniqueId('auth-method-key') },
    { value: 'password', labelKey: 'servers.authMethod.password', inputId: uniqueId('auth-method-password') },
  ];

  readonly steps: readonly ServerFormStep[] = this.editing
    ? ['connection', 'project']
    : ['connection', 'hostKey', 'project'];
  readonly stepLabels = STEP_LABELS;

  readonly step = signal(0);
  readonly onLastStep = computed(() => this.step() === this.steps.length - 1);

  readonly draft = signal<ServerDraft>(this.editing ? draftOf(this.editing) : NEW_SERVER);

  readonly hostKey = signal<HostKey | null>(null);
  readonly hostKeyConfirmed = signal(false);

  readonly saving = this.store.saving;
  readonly saveError = this.store.saveError;
  readonly fetchingHostKey = this.store.fetchingHostKey;
  readonly hostKeyError = this.store.hostKeyError;

  private readonly attempted = signal<ReadonlySet<ServerFormStep>>(new Set());

  private readonly edited = signal<ReadonlySet<ServerDraftField>>(new Set());

  private readonly problems = computed(() =>
    problemsIn(this.draft(), this.editing, this.hostKey(), this.hostKeyConfirmed()),
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
    () => this.editing !== null && changesMoreThanName(settingsOf(draftOf(this.editing)), settingsOf(this.draft())),
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

  readonly keySaved = computed(() => this.editing?.has_private_key ?? false);
  readonly keyPassphraseSaved = computed(() => this.editing?.has_key_passphrase ?? false);
  readonly passwordSaved = computed(() => this.editing?.has_password ?? false);

  constructor() {
    this.store.resetForm();
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

  // PrimeNG prints a step's value as its number, so values count from 1.
  stepValue(step: ServerFormStep): number {
    return this.steps.indexOf(step) + 1;
  }

  stepOpen(step: ServerFormStep): boolean {
    const index = this.steps.indexOf(step);
    return this.editing !== null || index <= this.step() || this.steps.slice(0, index).every((before) => this.stepDone(before));
  }

  goTo(value: number | undefined): void {
    if (value !== undefined) {
      this.step.set(value - 1);
    }
  }

  update<K extends keyof ServerDraft>(field: K, value: ServerDraft[K]): void {
    this.draft.update((draft) => ({ ...draft, [field]: value }));
    this.edited.update((edited) => new Set(edited).add(field));
    if (field === 'host' || field === 'port') {
      this.hostKey.set(null);
      this.hostKeyConfirmed.set(false);
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

  setFileRoots(roots: string[] | null): void {
    this.update('file_roots', roots ?? []);
  }

  async fetchHostKey(): Promise<void> {
    const { host, port } = this.draft();
    this.hostKeyConfirmed.set(false);
    this.hostKey.set(null);
    this.edited.update((edited) => new Set(edited).add('host_key'));
    this.hostKey.set(await this.store.fetchHostKey({ host: host.trim(), port: port ?? 22 }));
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
    const hostKey = this.hostKey();
    const password = this.passwordShown() && this.accountPassword() ? { account_password: this.accountPassword() } : {};
    const saved = this.editing
      ? await this.store.update(this.editing.id, { ...settingsOf(draft), ...password })
      : hostKey
        ? await this.store.create(creationOf(draft, hostKey))
        : null;

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
  editing: Server | null,
  hostKey: HostKey | null,
  hostKeyConfirmed: boolean,
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
  if (draft.auth_method === 'key' && draft.private_key.trim() === '' && !editing?.has_private_key) {
    problems.set('private_key', 'required');
  }
  if (draft.auth_method === 'password' && draft.password === '' && !editing?.has_password) {
    problems.set('password', 'required');
  }
  if (!editing) {
    if (!hostKey) {
      problems.set('host_key', 'host_key_missing');
    } else if (!hostKeyConfirmed) {
      problems.set('host_key', 'host_key_unconfirmed');
    }
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
    ...NEW_SERVER,
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

function creationOf(draft: ServerDraft, hostKey: HostKey): ServerCreate {
  return {
    ...settingsOf(draft),
    host_key: hostKey.line,
    ...(draft.backup_passphrase ? { backup_passphrase: draft.backup_passphrase } : {}),
  };
}
