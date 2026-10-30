import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import type { ApiError } from '@core/http/api.types';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Job } from '@core/jobs/job.types';
import { uniqueId } from '@shared/unique-id';
import type { RunRequest } from '@shared/confirmed-run/confirmed-run.types';
import { ConfirmedRun } from '@shared/confirmed-run/confirmed-run';
import { JobProgress } from '../job-progress/job-progress';

@Component({
  selector: 'app-revert-panel',
  imports: [ConfirmedRun, JobProgress, TranslatePipe],
  templateUrl: './revert-panel.html',
  styleUrl: './revert-panel.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RevertPanel {
  readonly prefix = input.required<string>();
  readonly expectedName = input.required<string>();
  readonly busy = input(false);
  readonly rehearsing = input(false);
  readonly error = input<ApiError | null>(null);
  readonly job = input<Job | null>(null);

  readonly run = output<RunRequest>();
  readonly edited = output();

  protected readonly headingId = uniqueId('revert');
}
