import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { MatProgressBar } from '@angular/material/progress-bar';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Job } from '@core/jobs/job.types';
import { FileSizePipe } from '@shared/file-size/file-size.pipe';
import { JobConnection } from '@shared/job-connection/job-connection';
import { Notice } from '@shared/notice/notice';
import { StepsList } from '@shared/steps-list/steps-list';
import type { ListedStep } from '@shared/steps-list/steps-list.types';
import { moveDetailOf } from '../../data/move-detail';
import type { MovePhase } from '../../data/relocation.types';
import type { ListedPhase } from './move-progress.types';

@Component({
  selector: 'app-move-progress',
  imports: [MatProgressBar, FileSizePipe, JobConnection, Notice, StepsList, ErrorTextPipe, TranslatePipe],
  templateUrl: './move-progress.html',
  styleUrl: './move-progress.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MoveProgress {
  private readonly locale = inject(LocaleStore);

  readonly job = input.required<Job>();

  protected readonly detail = computed(() => moveDetailOf(this.job().detail));
  protected readonly current = computed(() => this.detail().current);
  protected readonly percent = computed(() => {
    const current = this.current();
    return current?.total && current.bytes !== undefined ? Math.min(100, (100 * current.bytes) / current.total) : null;
  });

  protected readonly phases = computed<readonly ListedPhase[]>(() =>
    this.detail()
      .phases.filter((phase) => !this.detail().rehearsal || phase.phase === 'plan')
      .map((phase, position) => ({
        key: `${position}-${phase.phase}-${phase.name ?? ''}`,
        title: this.titleOf(phase),
        steps: phase.steps.map((step, index) => this.listed(step.step, step.key, step.status, `${position}-${index}`)),
      })),
  );

  private titleOf(phase: MovePhase): string {
    if (phase.phase === 'application') {
      return this.locale.translate('relocation.phases.application', {
        name: phase.name ?? '',
        target: phase.target_name ?? '',
      });
    }
    return this.locale.translate(`relocation.phases.${phase.phase}`);
  }

  private listed(step: string, key: string | undefined, status: ListedStep['status'], id: string): ListedStep {
    const label = this.locale.translate(`relocation.steps.${step}`);
    return {
      key: id,
      label: key ? `${label}: ${key}` : label,
      status,
      statusLabel: this.locale.translate(`relocation.status.${status}`),
    };
  }
}
