import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { JobConnection as Connection } from '@core/jobs/job.types';
import { FileSizePipe } from '@shared/file-size/file-size.pipe';
import { StatusTag } from '@shared/status-tag/status-tag';
import { TimeAgoPipe } from '@shared/time-ago/time-ago.pipe';

@Component({
  selector: 'app-job-connection',
  imports: [StatusTag, FileSizePipe, TimeAgoPipe, TranslatePipe],
  templateUrl: './job-connection.html',
  styleUrl: './job-connection.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { role: 'status' },
})
export class JobConnection {
  readonly connection = input.required<Connection>();

  protected readonly alive = computed(() => this.connection().state === 'alive');
}
