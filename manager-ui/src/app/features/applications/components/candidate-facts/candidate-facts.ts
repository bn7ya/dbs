import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { TranslatePipe } from '@core/i18n/translate.pipe';
import { Notice } from '@shared/notice/notice';
import { StatusTag } from '@shared/status-tag/status-tag';
import type { Candidate, DeploymentQuestion } from '../../data/applications.types';
import { answerKey } from '../../data/deployment';
import { NextSteps } from '../next-steps/next-steps';

@Component({
  selector: 'app-candidate-facts',
  imports: [NextSteps, Notice, StatusTag, TranslatePipe],
  templateUrl: './candidate-facts.html',
  styleUrl: './candidate-facts.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CandidateFacts {
  readonly candidate = input.required<Candidate>();

  protected readonly contained = computed(() => this.candidate().kind !== 'host');
  protected readonly mismatches = computed(() => this.candidate().mismatches ?? []);
  protected readonly backupDirElsewhere = computed(() => {
    const candidate = this.candidate();
    return candidate.backup_dir_on_host !== null && candidate.backup_dir_on_host !== candidate.remote_backup_dir;
  });

  answer(question: DeploymentQuestion, value: string): string {
    return answerKey(question, value);
  }
}
