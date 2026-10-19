import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import type { Job } from '@core/jobs/job.types';
import { JobConnection } from '@shared/job-connection/job-connection';
import { Notice } from '@shared/notice/notice';
import { StepsList } from '@shared/steps-list/steps-list';
import type { ListedStep } from '@shared/steps-list/steps-list.types';
import { failedStepOf, isRehearsal, jobStepsOf } from '../../data/job-detail';

@Component({
  selector: 'app-job-progress',
  imports: [JobConnection, Notice, StepsList, ErrorTextPipe],
  templateUrl: './job-progress.html',
  styleUrl: './job-progress.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class JobProgress {
  private readonly locale = inject(LocaleStore);

  readonly job = input.required<Job>();
  readonly prefix = input.required<string>();
  readonly labels = input.required<string>();
  readonly headingLevel = input<3 | 4>(3);

  private readonly rehearsal = computed(() => isRehearsal(this.job().detail));

  readonly title = computed(() => this.locale.translate(`${this.prefix()}.${this.rehearsal() ? 'rehearsal' : 'title'}`));

  readonly done = computed(() => this.locale.translate(`${this.prefix()}.${this.rehearsal() ? 'rehearsed' : 'done'}`));

  readonly steps = computed<readonly ListedStep[]>(() =>
    jobStepsOf(this.job().detail).map((step, position) => ({
      key: `${position}-${step.step}`,
      label: this.locale.translate(`${this.labels()}.${step.step}`),
      status: step.status,
      statusLabel: this.locale.translate(`redeploy.status.${step.status}`),
    })),
  );

  readonly stoppedAt = computed(() => {
    const failed = failedStepOf(this.job().detail);
    if (failed === null) {
      return '';
    }
    const step = this.locale.translate(`${this.labels()}.${failed}`);
    return this.locale.translate(`${this.prefix()}.stoppedAt`, { step });
  });
}
