import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { TranslatePipe } from '@core/i18n/translate.pipe';
import { StatusTag } from '@shared/status-tag/status-tag';
import type { RedeployStep, RedeployStepStatus } from '../../data/redeploy.types';
import type { StepLook } from './move-steps.types';

const STEP_LOOKS: Readonly<Record<RedeployStepStatus, StepLook>> = {
  pending: { severity: 'neutral', icon: 'fa-solid fa-clock' },
  running: { severity: 'info', icon: 'fa-solid fa-spinner' },
  succeeded: { severity: 'success', icon: 'fa-solid fa-circle-check' },
  failed: { severity: 'danger', icon: 'fa-solid fa-circle-xmark' },
  skipped: { severity: 'neutral', icon: 'fa-solid fa-circle-minus' },
};

@Component({
  selector: 'app-move-steps',
  imports: [StatusTag, TranslatePipe],
  templateUrl: './move-steps.html',
  styleUrl: './move-steps.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MoveSteps {
  readonly steps = input.required<readonly RedeployStep[]>();
  readonly labels = input.required<string>();

  look(status: RedeployStepStatus): StepLook {
    return STEP_LOOKS[status] ?? STEP_LOOKS.pending;
  }
}
