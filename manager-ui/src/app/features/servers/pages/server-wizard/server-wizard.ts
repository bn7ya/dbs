import { COMMA, ENTER } from '@angular/cdk/keycodes';
import { ChangeDetectionStrategy, Component, afterRenderEffect, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatAutocomplete, MatAutocompleteTrigger } from '@angular/material/autocomplete';
import { MatButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { MatCheckbox } from '@angular/material/checkbox';
import { MatChipGrid, MatChipInput, MatChipRemove, MatChipRow, type MatChipInputEvent } from '@angular/material/chips';
import { MatOption } from '@angular/material/core';
import { MatError, MatFormField, MatHint, MatLabel } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';
import { MatRadioButton, MatRadioGroup } from '@angular/material/radio';
import { MatStep, MatStepper, MatStepperIcon } from '@angular/material/stepper';
import { RouterLink } from '@angular/router';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { CopyButton } from '@shared/copy-button/copy-button';
import { FieldError } from '@shared/field/field-error';
import { Notice } from '@shared/notice/notice';
import { PasswordInput } from '@shared/password-input/password-input';
import { StatusTag } from '@shared/status-tag/status-tag';
import { parseSnippet, versionBelow } from '../../data/connection-snippet';
import type { Discovery, HostKey, ProjectSettings, ServerCreate } from '../../data/servers.types';
import { ServerWizardStore } from '../../state/server-wizard.store';
import type { FingerprintMatch, SignInChoice, WizardDraft, WizardField, WizardStep } from './server-wizard.types';

const STEPS: readonly WizardStep[] = ['snippet', 'connection', 'signIn', 'project', 'check', 'passphrase', 'backup'];

const SIGN_IN_CHOICES: readonly SignInChoice[] = ['generate', 'key', 'password'];

const HEALTH_SUPPORT = '0.5.0';

const ABSOLUTE_PATH = /^\//;

const NEW_DRAFT: WizardDraft = {
  name: '',
  host: '',
  port: 22,
  username: '',
  sign_in: 'generate',
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

const FIELD_STEPS: Readonly<Partial<Record<WizardField, WizardStep>>> = {
  snippet: 'snippet',
  name: 'connection',
  host: 'connection',
  port: 'connection',
  username: 'connection',
  host_key: 'connection',
  private_key: 'signIn',
  password: 'signIn',
  project_dir: 'project',
  remote_backup_dir: 'project',
  env_path: 'project',
  file_roots: 'project',
};

@Component({
  selector: 'app-server-wizard',
  imports: [
    FormsModule,
    RouterLink,
    MatAutocomplete,
    MatAutocompleteTrigger,
    MatButton,
    MatCard,
    MatCardContent,
    MatCheckbox,
    MatChipGrid,
    MatChipInput,
    MatChipRemove,
    MatChipRow,
    MatError,
    MatFormField,
    MatHint,
    MatInput,
    MatLabel,
    MatOption,
    MatRadioButton,
    MatRadioGroup,
    MatStep,
    MatStepper,
    MatStepperIcon,
    CopyButton,
    FieldError,
    Notice,
    PasswordInput,
    StatusTag,
    ErrorTextPipe,
    TranslatePipe,
  ],
  templateUrl: './server-wizard.html',
  styleUrl: './server-wizard.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ServerWizardPage {
  private readonly store = inject(ServerWizardStore);

  readonly steps = STEPS;
  readonly signInChoices = SIGN_IN_CHOICES;
  readonly separators = [ENTER, COMMA];

  readonly step = signal(0);
  protected readonly shownStep = signal(0);
  private readonly attempted = signal<ReadonlySet<WizardStep>>(new Set());

  readonly snippetText = signal('');
  readonly parsed = computed(() => parseSnippet(this.snippetText()));
  readonly fromSnippet = signal(false);

  readonly draft = signal<WizardDraft>(NEW_DRAFT);
  readonly hostKey = signal<HostKey | null>(null);
  readonly hostKeyConfirmed = signal(false);
  readonly discovery = signal<Discovery | null>(null);

  readonly server = this.store.server;
  readonly publicKey = this.store.publicKey;
  readonly checked = this.store.checked;
  readonly captured = this.store.captured;
  readonly backupJob = this.store.backupJob;

  readonly fetchingHostKey = this.store.fetchingHostKey;
  readonly hostKeyError = this.store.hostKeyError;
  readonly creating = this.store.creating;
  readonly createError = this.store.createError;
  readonly readingKey = this.store.readingKey;
  readonly keyError = this.store.keyError;
  readonly discovering = this.store.discovering;
  readonly discoverError = this.store.discoverError;
  readonly savingProject = this.store.savingProject;
  readonly projectError = this.store.projectError;
  readonly checking = this.store.checking;
  readonly checkError = this.store.checkError;
  readonly capturing = this.store.capturing;
  readonly captureError = this.store.captureError;
  readonly backingUp = this.store.backingUp;
  readonly backupError = this.store.backupError;

  readonly created = computed(() => this.server() !== null);
  readonly busy = computed(() => this.creating() || this.savingProject() || this.checking());

  readonly fingerprintMatch = computed<FingerprintMatch | null>(() => {
    const key = this.hostKey();
    const snippet = this.parsed().snippet;
    if (!key || !snippet || snippet.host_keys.length === 0) {
      return null;
    }
    return snippet.host_keys.some((each) => each.fingerprint === key.fingerprint) ? 'match' : 'mismatch';
  });

  readonly remoteTooOld = computed(() => {
    const remote = this.checked()?.remote_version;
    return remote !== null && remote !== undefined && versionBelow(remote, HEALTH_SUPPORT);
  });

  readonly incompatible = computed(() => this.checked()?.compatible === false);

  readonly authorizedKeysPath = computed(() => `~${this.draft().username}/.ssh/authorized_keys`);

  private readonly problems = computed<ReadonlyMap<WizardField, string>>(() =>
    problemsIn(this.draft(), this.parsed().error, this.hostKey(), this.hostKeyConfirmed()),
  );

  constructor() {
    afterRenderEffect({ write: () => this.shownStep.set(this.step()) });
  }

  error(field: WizardField): string | null {
    const step = FIELD_STEPS[field];
    const own = step && this.attempted().has(step) ? this.problems().get(field) : undefined;
    return own ?? this.createError()?.fields?.[field]?.[0] ?? this.projectError()?.fields?.[field]?.[0] ?? null;
  }

  stepDone(step: WizardStep): boolean {
    return STEPS.indexOf(step) < this.step() && this.stepReady(step);
  }

  update<K extends keyof WizardDraft>(field: K, value: WizardDraft[K]): void {
    this.draft.update((draft) => ({ ...draft, [field]: value }));
    if (field === 'host' || field === 'port') {
      this.hostKey.set(null);
      this.hostKeyConfirmed.set(false);
    }
  }

  setSignIn(choice: SignInChoice | null): void {
    if (choice) {
      this.update('sign_in', choice);
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

  async fetchHostKey(): Promise<void> {
    const { host, port } = this.draft();
    this.hostKey.set(null);
    this.hostKeyConfirmed.set(false);
    this.hostKey.set(await this.store.fetchHostKey({ host: host.trim(), port: port ?? 22 }));
  }

  async discover(): Promise<void> {
    const found = await this.store.discover();
    if (!found) {
      return;
    }
    this.discovery.set(found);
    this.draft.update((draft) => ({
      ...draft,
      project_dir: found.project_dir || draft.project_dir,
      python_path: found.python_path || draft.python_path,
      manage_path: found.manage_path || draft.manage_path,
      settings_module: found.settings_module || draft.settings_module,
      remote_backup_dir: found.remote_backup_dir || draft.remote_backup_dir,
      file_roots: found.file_roots.length > 0 ? found.file_roots : draft.file_roots,
      env_path: found.env_path || draft.env_path,
    }));
  }

  rereadPublicKey(): void {
    void this.store.rereadPublicKey();
  }

  check(): void {
    void this.store.check();
  }

  capturePassphrase(): void {
    void this.store.capturePassphrase();
  }

  takeBackup(): void {
    this.store.takeBackup();
  }

  back(): void {
    this.step.update((step) => Math.max(this.created() ? STEPS.indexOf('project') : 0, step - 1));
  }

  skipProject(): void {
    this.step.set(STEPS.indexOf('check'));
  }

  async advance(): Promise<void> {
    const step = STEPS[this.step()];
    this.attempted.update((attempted) => new Set(attempted).add(step));
    if (!this.stepReady(step)) {
      return;
    }
    if (step === 'snippet') {
      this.applySnippet();
    } else if (step === 'signIn' && !(await this.createOnce())) {
      return;
    } else if (step === 'project' && !(await this.store.saveProject(projectOf(this.draft())))) {
      return;
    } else if (step === 'check' && !this.checkPassed()) {
      await this.store.check();
      return;
    }
    this.step.update((index) => Math.min(index + 1, STEPS.length - 1));
  }

  private checkPassed(): boolean {
    const checked = this.checked();
    return checked !== null && checked.compatible;
  }

  private stepReady(step: WizardStep): boolean {
    for (const field of this.problems().keys()) {
      if (FIELD_STEPS[field] === step) {
        return false;
      }
    }
    return true;
  }

  private applySnippet(): void {
    const snippet = this.parsed().snippet;
    if (!snippet) {
      return;
    }
    this.fromSnippet.set(true);
    this.draft.update((draft) => ({
      ...draft,
      name: snippet.hostname || draft.name,
      host: snippet.hostname || draft.host,
      username: snippet.ssh_user || draft.username,
      project_dir: snippet.project_dir || draft.project_dir,
      python_path: snippet.python_path || draft.python_path,
      manage_path: snippet.manage_path || draft.manage_path,
      settings_module: snippet.settings_module || draft.settings_module,
      remote_backup_dir: snippet.remote_backup_dir || draft.remote_backup_dir,
      file_roots: snippet.file_roots.length > 0 ? snippet.file_roots : draft.file_roots,
      env_path: snippet.env_path || draft.env_path,
    }));
  }

  private async createOnce(): Promise<boolean> {
    if (this.created()) {
      return true;
    }
    const hostKey = this.hostKey();
    if (!hostKey) {
      return false;
    }
    const created = await this.store.create(creationOf(this.draft(), hostKey));
    return created !== null && !created.public_key;
  }
}

function problemsIn(
  draft: WizardDraft,
  snippetError: string | null,
  hostKey: HostKey | null,
  confirmed: boolean,
): ReadonlyMap<WizardField, string> {
  const problems = new Map<WizardField, string>();
  if (snippetError) {
    problems.set('snippet', snippetError);
  }
  for (const field of ['name', 'host', 'username'] as const) {
    if (draft[field].trim() === '') {
      problems.set(field, 'required');
    }
  }
  const port = draft.port;
  if (port === null || !Number.isInteger(port) || port < 1 || port > 65535) {
    problems.set('port', 'port_range');
  }
  if (!hostKey) {
    problems.set('host_key', 'host_key_missing');
  } else if (!confirmed) {
    problems.set('host_key', 'host_key_unconfirmed');
  }
  if (draft.sign_in === 'key' && draft.private_key.trim() === '') {
    problems.set('private_key', 'required');
  }
  if (draft.sign_in === 'password' && draft.password === '') {
    problems.set('password', 'required');
  }
  if (draft.remote_backup_dir.trim() === '') {
    problems.set('remote_backup_dir', 'required');
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

function projectOf(draft: WizardDraft): ProjectSettings {
  return {
    project_dir: draft.project_dir.trim(),
    python_path: draft.python_path.trim(),
    manage_path: draft.manage_path.trim(),
    settings_module: draft.settings_module.trim(),
    remote_backup_dir: draft.remote_backup_dir.trim(),
    file_roots: draft.file_roots.map((root) => root.trim()),
    env_path: draft.env_path.trim(),
  };
}

function creationOf(draft: WizardDraft, hostKey: HostKey): ServerCreate {
  const secrets =
    draft.sign_in === 'generate'
      ? { auth_method: 'key' as const, generate_key: true }
      : draft.sign_in === 'key'
        ? {
            auth_method: 'key' as const,
            private_key: draft.private_key,
            ...(draft.key_passphrase ? { key_passphrase: draft.key_passphrase } : {}),
          }
        : { auth_method: 'password' as const, password: draft.password };
  return {
    name: draft.name.trim(),
    host: draft.host.trim(),
    port: draft.port ?? 22,
    username: draft.username.trim(),
    ...secrets,
    ...projectOf(draft),
    host_key: hostKey.line,
  };
}
