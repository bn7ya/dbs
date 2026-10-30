import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { MatRadioButton, MatRadioGroup } from '@angular/material/radio';

import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { DeploymentProfile, DeploymentQuestion } from '../../data/applications.types';
import { DEPLOYMENT_QUESTIONS, answerKey, answerOf, asks, withAnswer } from '../../data/deployment';
import type { QuestionDefinition } from '../../data/deployment.types';

@Component({
  selector: 'app-deployment-questions',
  imports: [MatRadioButton, MatRadioGroup, TranslatePipe],
  templateUrl: './deployment-questions.html',
  styleUrl: './deployment-questions.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DeploymentQuestions {
  readonly profile = input.required<DeploymentProfile>();
  readonly detected = input<DeploymentProfile | null | undefined>(null);
  readonly changed = output<DeploymentProfile>();

  protected readonly questions = computed<readonly QuestionDefinition[]>(() =>
    DEPLOYMENT_QUESTIONS.filter((question) => asks(question.key, this.profile())),
  );

  answer(question: DeploymentQuestion): string {
    return answerOf(this.profile(), question);
  }

  found(question: DeploymentQuestion): string {
    const found = answerOf(this.detected(), question);
    return found && found !== this.answer(question) ? found : '';
  }

  label(question: DeploymentQuestion, value: string): string {
    return answerKey(question, value);
  }

  choose(question: DeploymentQuestion, value: unknown): void {
    this.changed.emit(withAnswer(this.profile(), question, typeof value === 'string' ? value : ''));
  }
}
