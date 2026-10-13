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

import type { ApiError } from '@core/http/api.types';
import { ErrorTextPipe, errorText } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { AppDatePipe } from '@shared/app-date/app-date.pipe';
import { FieldError } from '@shared/field/field-error';
import { JobConnection } from '@shared/job-connection/job-connection';
import { Notice } from '@shared/notice/notice';
import { PasswordInput } from '@shared/password-input/password-input';
import { MoveSteps } from '../../components/move-steps/move-steps';
import { RedeployStore } from '../../state/redeploy.store';
import type { Attempt } from './redeploy.types';

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
    JobConnection,
    MoveSteps,
    Notice,
    PasswordInput,
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
  readonly envVersions = this.store.envVersions;
  readonly loading = this.store.loading;
  readonly loadError = this.store.loadError;
  readonly running = this.store.running;
  readonly runError = this.store.runError;
  readonly job = this.store.job;
  readonly steps = this.store.steps;
  readonly outcome = this.store.outcome;
  readonly rehearsing = this.store.rehearsal;
  readonly reverting = this.store.reverting;
  readonly revertJob = this.store.revertJob;
  readonly revertSteps = this.store.revertSteps;
  readonly revertRehearsing = this.store.revertRehearsal;

  readonly target = signal<string | null>(null);
  readonly backup = linkedSignal<string | null>(() => this.backups()[0]?.id ?? null);
  readonly envVersion = linkedSignal<string | null>(() => this.envVersions()[0]?.id ?? null);
  readonly flush = signal(false);
  readonly password = signal('');
  readonly confirmName = signal('');
  readonly revertPassword = signal('');
  readonly revertName = signal('');
  private readonly attempt = signal<Attempt | null>(null);
  private readonly revertAttempt = signal<Attempt | null>(null);

  readonly targetName = computed(() => this.targets().find((server) => server.id === this.target())?.name ?? '');
  readonly targetMissing = computed(() => this.attempt() !== null && this.target() === null);

  readonly passwordError = this.passwordProblem(this.attempt, this.password, this.runError);
  readonly nameError = this.nameProblem(this.attempt, this.confirmName, this.runError);
  readonly formFailure = computed(() => notAboutAField(this.runError()));

  readonly revertPasswordError = this.passwordProblem(this.revertAttempt, this.revertPassword, this.store.revertError);
  readonly revertNameError = this.nameProblem(this.revertAttempt, this.revertName, this.store.revertError);
  readonly revertFailure = computed(() => notAboutAField(this.store.revertError()));

  constructor() {
    effect(() => this.store.open(this.serverId()));
  }

  setPassword(value: string): void {
    this.password.set(value);
    this.store.clearError();
  }

  setConfirmName(value: string): void {
    this.confirmName.set(value);
    this.store.clearError();
  }

  setRevertPassword(value: string): void {
    this.revertPassword.set(value);
    this.store.clearRevertError();
  }

  setRevertName(value: string): void {
    this.revertName.set(value);
    this.store.clearRevertError();
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

  rehearseRevert(): void {
    this.submitRevert('rehearsal');
  }

  revertForReal(): void {
    this.submitRevert('real');
  }

  private submit(attempt: Attempt): void {
    this.attempt.set(attempt);
    const source = this.serverId();
    const target = this.target();
    if (source === null || target === null) {
      return;
    }
    if (attempt === 'real' && (this.passwordError() !== '' || this.nameError() !== '')) {
      return;
    }
    const rehearsal = attempt === 'rehearsal';
    this.revertAttempt.set(null);
    this.store.run({
      source_server: source,
      target_server: target,
      backup: this.backup(),
      env_version: this.envVersion(),
      flush: this.flush(),
      rehearsal,
      password: rehearsal ? '' : this.password(),
      confirm_name: rehearsal ? '' : this.confirmName().trim(),
    });
  }

  private submitRevert(attempt: Attempt): void {
    this.revertAttempt.set(attempt);
    if (attempt === 'real' && (this.revertPasswordError() !== '' || this.revertNameError() !== '')) {
      return;
    }
    const rehearsal = attempt === 'rehearsal';
    this.store.revert({
      rehearsal,
      password: rehearsal ? '' : this.revertPassword(),
      confirm_name: rehearsal ? '' : this.revertName().trim(),
    });
  }

  private passwordProblem(
    attempt: Signal<Attempt | null>,
    password: Signal<string>,
    failure: Signal<ApiError | null>,
  ): Signal<string> {
    return computed(() => {
      if (attempt() === 'real' && password() === '') {
        return this.locale.translate('password.required');
      }
      return failure()?.code === 'invalid_password' ? errorText(this.locale, 'invalid_password') : '';
    });
  }

  private nameProblem(
    attempt: Signal<Attempt | null>,
    typed: Signal<string>,
    failure: Signal<ApiError | null>,
  ): Signal<string> {
    return computed(() => {
      if (attempt() === 'real' && this.target() !== null && typed().trim() !== this.targetName()) {
        return errorText(this.locale, 'confirm_name_mismatch');
      }
      return failure()?.code === 'confirm_name_mismatch' ? errorText(this.locale, 'confirm_name_mismatch') : '';
    });
  }
}

function notAboutAField(failure: ApiError | null): ApiError | null {
  return failure && !FIELD_FAILURES.has(failure.code) ? failure : null;
}

function serverIdOf(route: ActivatedRoute): Signal<string | null> {
  const owner = route.pathFromRoot.find((step) => step.snapshot.paramMap.has('serverId'));
  if (!owner) {
    return signal(null).asReadonly();
  }
  return toSignal(owner.paramMap.pipe(map((params) => params.get('serverId'))), { requireSync: true });
}
