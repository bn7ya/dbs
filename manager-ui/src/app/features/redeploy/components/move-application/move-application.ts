import { ChangeDetectionStrategy, Component, computed, inject, linkedSignal, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { MatCheckbox } from '@angular/material/checkbox';
import { MatOption } from '@angular/material/core';
import { MatError, MatFormField, MatHint, MatLabel } from '@angular/material/form-field';
import { MatSelect } from '@angular/material/select';
import { RouterLink } from '@angular/router';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { AppDatePipe } from '@shared/app-date/app-date.pipe';
import { FieldError } from '@shared/field/field-error';
import { isolated } from '@shared/isolated/isolated';
import { Notice } from '@shared/notice/notice';
import { uniqueId } from '@shared/unique-id';
import type { RunRequest } from '../../data/redeploy.types';
import { MoveStore } from '../../state/move.store';
import { ConfirmedRun } from '../confirmed-run/confirmed-run';
import { JobProgress } from '../job-progress/job-progress';
import { RevertPanel } from '../revert-panel/revert-panel';
import type { TargetOption } from './move-application.types';

@Component({
  selector: 'app-move-application',
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
    MatLabel,
    MatOption,
    MatSelect,
    ConfirmedRun,
    FieldError,
    JobProgress,
    Notice,
    RevertPanel,
    AppDatePipe,
    ErrorTextPipe,
    TranslatePipe,
  ],
  templateUrl: './move-application.html',
  styleUrl: './move-application.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MoveApplication {
  readonly headingId = uniqueId('move-title');

  private readonly store = inject(MoveStore);
  private readonly locale = inject(LocaleStore);

  readonly backups = this.store.backups;
  readonly envVersions = this.store.envVersions;
  readonly loading = this.store.loading;
  readonly loadError = this.store.loadError;
  readonly moving = this.store.moving;
  readonly reverting = this.store.reverting;
  readonly outcome = this.store.outcome;

  readonly target = signal<string | null>(null);
  readonly backup = linkedSignal<string | null>(() => this.backups()[0]?.id ?? null);
  readonly envVersion = linkedSignal<string | null>(() => this.envVersions()[0]?.id ?? null);
  readonly flush = signal(false);
  private readonly attempted = signal(false);

  readonly targets = computed<readonly TargetOption[]>(() =>
    this.store.targets().map((application) => ({
      id: application.id,
      label: this.locale.translate('redeploy.move.targetOption', {
        name: isolated(application.name),
        server: isolated(application.server.name),
      }),
    })),
  );

  readonly targetName = computed(
    () => this.store.targets().find((application) => application.id === this.target())?.name ?? '',
  );

  readonly targetMissing = computed(() => this.attempted() && this.target() === null);

  readonly movedToName = computed(() => this.store.movedTo()?.name ?? '');

  onAttempt(): void {
    this.attempted.set(true);
  }

  move(request: RunRequest): void {
    const source = this.store.source();
    const target = this.target();
    if (source === null || target === null) {
      return;
    }
    this.store.move({
      ...request,
      source_application: source,
      target_application: target,
      backup: this.backup(),
      env_version: this.envVersion(),
      flush: this.flush(),
    });
  }

  revert(request: RunRequest): void {
    this.store.revert(request);
  }

  clearError(): void {
    this.moving.clearError();
  }

  clearRevertError(): void {
    this.reverting.clearError();
  }

  retry(): void {
    this.store.reload();
  }
}
