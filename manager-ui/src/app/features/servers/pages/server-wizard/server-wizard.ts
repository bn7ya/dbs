import { ChangeDetectionStrategy, Component, afterRenderEffect, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { MatCheckbox } from '@angular/material/checkbox';
import { MatError, MatFormField, MatHint, MatLabel } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';
import { MatRadioButton, MatRadioGroup } from '@angular/material/radio';
import { MatStep, MatStepper, MatStepperIcon } from '@angular/material/stepper';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { Can } from '@core/auth/directives/can';
import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { CopyButton } from '@shared/copy-button/copy-button';
import { FieldError } from '@shared/field/field-error';
import { isolated } from '@shared/isolated/isolated';
import { Notice } from '@shared/notice/notice';
import { PasswordInput } from '@shared/password-input/password-input';
import { uniqueId } from '@shared/unique-id';
import { EnginesReport } from '../../components/engines-report/engines-report';
import { HostKeyFacts } from '../../components/host-key-facts/host-key-facts';
import type { HostKey, ServerCreate } from '../../data/servers.types';
import { ServerWizardStore } from '../../state/server-wizard.store';
import type { SignInChoice, WizardDraft, WizardField, WizardStep } from './server-wizard.types';

const STEPS: readonly WizardStep[] = ['address', 'hostKey', 'signIn', 'check', 'done'];

const SIGN_IN_CHOICES: readonly SignInChoice[] = ['generate', 'key', 'password'];

const FIRST_AFTER_CREATION = STEPS.indexOf('check');

const MOVE_PATH = /^\/servers\/[0-9a-f-]{36}\/move$/;

const NEW_DRAFT: WizardDraft = {
  name: '',
  host: '',
  port: 22,
  username: '',
  sign_in: 'generate',
  private_key: '',
  key_passphrase: '',
  password: '',
};

const FIELD_STEPS: Readonly<Partial<Record<WizardField, WizardStep>>> = {
  name: 'address',
  host: 'address',
  port: 'address',
  username: 'address',
  host_key: 'hostKey',
  private_key: 'signIn',
  password: 'signIn',
};

@Component({
  selector: 'app-server-wizard',
  imports: [
    Can,
    FormsModule,
    RouterLink,
    MatButton,
    MatCard,
    MatCardContent,
    MatCheckbox,
    MatError,
    MatFormField,
    MatHint,
    MatInput,
    MatLabel,
    MatRadioButton,
    MatRadioGroup,
    MatStep,
    MatStepper,
    MatStepperIcon,
    CopyButton,
    EnginesReport,
    FieldError,
    HostKeyFacts,
    Notice,
    PasswordInput,
    ErrorTextPipe,
    TranslatePipe,
  ],
  templateUrl: './server-wizard.html',
  styleUrl: './server-wizard.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ServerWizardPage {
  private readonly store = inject(ServerWizardStore);
  private readonly route = inject(ActivatedRoute);

  readonly steps = STEPS;
  readonly signInChoices = SIGN_IN_CHOICES;
  readonly firstAfterCreation = FIRST_AFTER_CREATION;
  readonly signInStep = STEPS.indexOf('signIn');
  protected readonly confirmId = uniqueId('host-key-confirmed');
  readonly returnTo = moveReturn(this.route.snapshot.queryParamMap.get('returnTo'));

  readonly step = signal(0);
  protected readonly shownStep = signal(0);
  private readonly attempted = signal<ReadonlySet<WizardStep>>(new Set());

  readonly draft = signal<WizardDraft>(NEW_DRAFT);
  readonly hostKey = signal<HostKey | null>(null);
  readonly hostKeyConfirmed = signal(false);

  readonly server = this.store.server;
  readonly publicKey = this.store.publicKey;
  readonly checked = this.store.checked;

  readonly fetchingHostKey = this.store.fetchingHostKey;
  readonly hostKeyError = this.store.hostKeyError;
  readonly creating = this.store.creating;
  readonly createError = this.store.createError;
  readonly createFailure = computed(() => {
    const failure = this.createError();
    return failure && !failure.fields ? failure : null;
  });
  readonly readingKey = this.store.readingKey;
  readonly keyError = this.store.keyError;
  readonly checking = this.store.checking;
  readonly checkError = this.store.checkError;

  readonly created = computed(() => this.server() !== null);
  readonly busy = computed(() => this.creating() || this.checking() || this.fetchingHostKey());

  readonly authorizedKeysPath = computed(() => isolated(`~${this.draft().username.trim()}/.ssh/authorized_keys`));

  readonly reported = computed(() => {
    const status = this.checked()?.last_check_status;
    return status === 'ok' || status === 'problem';
  });

  readonly keyRefused = computed(() => this.checkError()?.code === 'ssh_auth_failed' && this.publicKey() !== null);

  private readonly problems = computed<ReadonlyMap<WizardField, string>>(() =>
    problemsIn(this.draft(), this.hostKey(), this.hostKeyConfirmed()),
  );

  constructor() {
    afterRenderEffect({ write: () => this.shownStep.set(this.step()) });
  }

  error(field: WizardField): string | null {
    const step = FIELD_STEPS[field];
    const own = step && this.attempted().has(step) ? this.problems().get(field) : undefined;
    return own ?? this.createError()?.fields?.[field]?.[0] ?? null;
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

  async fetchHostKey(): Promise<void> {
    const { host, port } = this.draft();
    this.hostKey.set(null);
    this.hostKeyConfirmed.set(false);
    this.hostKey.set(await this.store.fetchHostKey({ host: host.trim(), port: port ?? 22 }));
  }

  rereadPublicKey(): void {
    void this.store.rereadPublicKey();
  }

  check(): void {
    void this.store.check();
  }

  back(): void {
    this.step.update((step) => Math.max(this.created() ? FIRST_AFTER_CREATION : 0, step - 1));
  }

  async advance(): Promise<void> {
    if (this.busy()) {
      return;
    }
    const step = STEPS[this.step()];
    this.attempted.update((attempted) => new Set(attempted).add(step));
    if (!this.stepReady(step)) {
      if (step === 'check') {
        await this.store.check();
      }
      return;
    }
    if (step === 'signIn' && !(await this.createOnce())) {
      return;
    }
    this.step.update((index) => Math.min(index + 1, STEPS.length - 1));
    this.arrive(STEPS[this.step()]);
  }

  private arrive(step: WizardStep): void {
    if (step === 'hostKey' && this.hostKey() === null) {
      void this.fetchHostKey();
    } else if (step === 'check') {
      void this.store.check();
    }
  }

  private stepReady(step: WizardStep): boolean {
    if (step === 'check') {
      return this.checked() !== null;
    }
    for (const field of this.problems().keys()) {
      if (FIELD_STEPS[field] === step) {
        return false;
      }
    }
    return true;
  }

  // A generated key stays on screen once, so it can be added to authorized_keys before the check.
  private async createOnce(): Promise<boolean> {
    if (this.created()) {
      return true;
    }
    const hostKey = this.hostKey();
    if (!hostKey) {
      return false;
    }
    const created = await this.store.create(creationOf(this.draft(), hostKey));
    if (created === null) {
      const failed = Object.keys(this.createError()?.fields ?? {})
        .map((field) => FIELD_STEPS[field as WizardField])
        .find((owner) => owner !== undefined);
      if (failed) {
        this.step.set(STEPS.indexOf(failed));
      }
      return false;
    }
    return !created.public_key;
  }
}

function problemsIn(draft: WizardDraft, hostKey: HostKey | null, confirmed: boolean): ReadonlyMap<WizardField, string> {
  const problems = new Map<WizardField, string>();
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
  return problems;
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
    host_key: hostKey.line,
  };
}

function moveReturn(path: string | null): string | null {
  return path !== null && MOVE_PATH.test(path) ? path : null;
}
