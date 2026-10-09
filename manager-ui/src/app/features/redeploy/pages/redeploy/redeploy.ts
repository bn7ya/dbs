import { ChangeDetectionStrategy, Component, computed, effect, inject, linkedSignal, signal, type Signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MatButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { MatCheckbox } from '@angular/material/checkbox';
import { MatOption } from '@angular/material/core';
import { MatError, MatFormField, MatHint, MatLabel } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';
import { MatSelect } from '@angular/material/select';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { map } from 'rxjs';

import { ErrorTextPipe, errorText } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { AppDatePipe } from '@shared/app-date/app-date.pipe';
import { FieldError } from '@shared/field/field-error';
import { Notice } from '@shared/notice/notice';
import { PasswordInput } from '@shared/password-input/password-input';
import { StatusTag } from '@shared/status-tag/status-tag';
import type { RedeployStepStatus } from '../../data/redeploy.types';
import { RedeployStore } from '../../state/redeploy.store';
import type { Attempt, StepLook } from './redeploy.types';

const STEP_LOOKS: Readonly<Record<RedeployStepStatus, StepLook>> = {
  pending: { severity: 'neutral', icon: 'fa-solid fa-clock' },
  running: { severity: 'info', icon: 'fa-solid fa-spinner' },
  succeeded: { severity: 'success', icon: 'fa-solid fa-circle-check' },
  failed: { severity: 'danger', icon: 'fa-solid fa-circle-xmark' },
  skipped: { severity: 'neutral', icon: 'fa-solid fa-circle-minus' },
};

const FIELD_FAILURES: ReadonlySet<string> = new Set(['invalid_password', 'confirm_name_mismatch']);

@Component({
  selector: 'app-redeploy-page',
  imports: [
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
    MatOption,
    MatSelect,
    FieldError,
    Notice,
    PasswordInput,
    StatusTag,
    AppDatePipe,
    ErrorTextPipe,
    TranslatePipe,
  ],
  templateUrl: './redeploy.html',
  styleUrl: './redeploy.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RedeployPage {
  private readonly store = inject(RedeployStore);
  private readonly locale = inject(LocaleStore);

  readonly serverId = serverIdOf(inject(ActivatedRoute));

  readonly targets = this.store.targets;
  readonly backups = this.store.backups;
  readonly archiveOptions = this.store.archives;
  readonly envVersions = this.store.envVersions;
  readonly loading = this.store.loading;
  readonly loadError = this.store.loadError;
  readonly running = this.store.running;
  readonly runError = this.store.runError;
  readonly job = this.store.job;
  readonly steps = this.store.steps;
  readonly rehearsing = this.store.rehearsal;

  readonly target = signal<string | null>(null);
  readonly backup = linkedSignal<string | null>(() => this.backups()[0]?.id ?? null);
  readonly envVersion = linkedSignal<string | null>(() => this.envVersions()[0]?.id ?? null);
  readonly archives = signal<readonly string[]>([]);
  readonly migrate = signal(true);
  readonly flush = signal(false);
  readonly password = signal('');
  readonly confirmName = signal('');
  private readonly attempt = signal<Attempt | null>(null);

  readonly targetName = computed(() => this.targets().find((server) => server.id === this.target())?.name ?? '');

  readonly targetMissing = computed(() => this.attempt() !== null && this.target() === null);
  readonly backupMissing = computed(() => this.attempt() !== null && this.backup() === null);
  private readonly real = computed(() => this.attempt() === 'real');

  readonly passwordError = computed(() => {
    if (this.real() && this.password() === '') {
      return this.locale.translate('password.required');
    }
    return this.runError()?.code === 'invalid_password' ? errorText(this.locale, 'invalid_password') : '';
  });

  readonly nameError = computed(() => {
    if (this.real() && this.target() !== null && this.confirmName().trim() !== this.targetName()) {
      return errorText(this.locale, 'confirm_name_mismatch');
    }
    return this.runError()?.code === 'confirm_name_mismatch' ? errorText(this.locale, 'confirm_name_mismatch') : '';
  });

  readonly formFailure = computed(() => {
    const failure = this.runError();
    return failure && !FIELD_FAILURES.has(failure.code) ? failure : null;
  });

  constructor() {
    effect(() => this.store.open(this.serverId()));
  }

  stepLook(status: RedeployStepStatus): StepLook {
    return STEP_LOOKS[status] ?? STEP_LOOKS.pending;
  }

  setPassword(value: string): void {
    this.password.set(value);
    this.store.clearError();
  }

  setConfirmName(value: string): void {
    this.confirmName.set(value);
    this.store.clearError();
  }

  retry(): void {
    this.store.reload();
  }

  rehearse(): void {
    this.submit('rehearsal');
  }

  moveForReal(): void {
    this.submit('real');
  }

  private submit(attempt: Attempt): void {
    this.attempt.set(attempt);
    const source = this.serverId();
    const target = this.target();
    const backup = this.backup();
    if (source === null || target === null || backup === null) {
      return;
    }
    if (attempt === 'real' && (this.passwordError() !== '' || this.nameError() !== '')) {
      return;
    }
    const rehearsal = attempt === 'rehearsal';
    this.store.run({
      source_server: source,
      target_server: target,
      backup,
      env_version: this.envVersion(),
      archives: [...this.archives()],
      migrate: this.migrate(),
      flush: this.flush(),
      rehearsal,
      password: rehearsal ? '' : this.password(),
      confirm_name: rehearsal ? '' : this.confirmName().trim(),
    });
  }
}

function serverIdOf(route: ActivatedRoute): Signal<string | null> {
  const owner = route.pathFromRoot.find((step) => step.snapshot.paramMap.has('serverId'));
  if (!owner) {
    return signal(null).asReadonly();
  }
  return toSignal(owner.paramMap.pipe(map((params) => params.get('serverId'))), { requireSync: true });
}
