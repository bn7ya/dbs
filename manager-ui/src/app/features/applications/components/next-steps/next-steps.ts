import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { TranslatePipe } from '@core/i18n/translate.pipe';
import { CopyButton } from '@shared/copy-button/copy-button';
import type { CheckProblem, DiscoveryProblem } from '../../data/applications.types';
import { nextSteps } from '../../data/deployment';
import type { NextStep, StepPlace } from '../../data/deployment.types';

@Component({
  selector: 'app-next-steps',
  imports: [CopyButton, TranslatePipe],
  templateUrl: './next-steps.html',
  styleUrl: './next-steps.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NextSteps {
  readonly problems = input.required<readonly (CheckProblem | DiscoveryProblem)[]>();
  readonly place = input.required<StepPlace>();

  protected readonly steps = computed<readonly NextStep[]>(() => nextSteps(this.problems(), this.place()));
}
