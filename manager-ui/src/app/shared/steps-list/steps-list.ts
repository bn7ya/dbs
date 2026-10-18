import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { StatusTag } from '../status-tag/status-tag';
import type { ListedStep, StepLook, StepStatus } from './steps-list.types';

const STEP_LOOKS: Readonly<Record<StepStatus, StepLook>> = {
  pending: { severity: 'neutral', icon: 'fa-solid fa-clock' },
  running: { severity: 'info', icon: 'fa-solid fa-spinner' },
  succeeded: { severity: 'success', icon: 'fa-solid fa-circle-check' },
  failed: { severity: 'danger', icon: 'fa-solid fa-circle-xmark' },
  skipped: { severity: 'neutral', icon: 'fa-solid fa-circle-minus' },
};

@Component({
  selector: 'app-steps-list',
  imports: [StatusTag],
  templateUrl: './steps-list.html',
  styleUrl: './steps-list.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StepsList {
  readonly steps = input.required<readonly ListedStep[]>();

  look(status: StepStatus): StepLook {
    return STEP_LOOKS[status] ?? STEP_LOOKS.pending;
  }
}
