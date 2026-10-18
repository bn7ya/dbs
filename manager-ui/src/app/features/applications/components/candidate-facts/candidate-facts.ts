import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { TranslatePipe } from '@core/i18n/translate.pipe';
import { StatusTag } from '@shared/status-tag/status-tag';
import type { Candidate } from '../../data/applications.types';

@Component({
  selector: 'app-candidate-facts',
  imports: [StatusTag, TranslatePipe],
  templateUrl: './candidate-facts.html',
  styleUrl: './candidate-facts.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CandidateFacts {
  readonly candidate = input.required<Candidate>();

  protected readonly contained = computed(() => this.candidate().kind !== 'host');
  protected readonly backupDirElsewhere = computed(() => {
    const candidate = this.candidate();
    return candidate.backup_dir_on_host !== null && candidate.backup_dir_on_host !== candidate.remote_backup_dir;
  });
}
