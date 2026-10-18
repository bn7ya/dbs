import { COMMA, ENTER } from '@angular/cdk/keycodes';
import { ChangeDetectionStrategy, Component, computed, inject, input, linkedSignal, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButton, MatIconButton } from '@angular/material/button';
import { MatCheckbox } from '@angular/material/checkbox';
import { MatChipGrid, MatChipInput, MatChipRemove, MatChipRow, type MatChipInputEvent } from '@angular/material/chips';
import { MatError, MatFormField, MatHint, MatLabel } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';
import { MatMenu, MatMenuItem, MatMenuTrigger } from '@angular/material/menu';

import { errorText } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { Dialogs } from '@shared/dialogs/dialogs';
import { FieldError } from '@shared/field/field-error';
import { Notice } from '@shared/notice/notice';
import { PasswordPrompt } from '@shared/password-prompt/password-prompt';
import type { PasswordPromptData } from '@shared/password-prompt/password-prompt.types';
import {
  DEPLOY_STEPS_MAX,
  DEPLOY_TIMEOUT_MAX,
  DEPLOY_TIMEOUT_MIN,
  fitProblems,
  isStepProblem,
  kindsFor,
  takesServices,
} from '../../data/deploy-catalogue';
import type { DeployApplication, DeployStepKind } from '../../data/redeploy.types';
import { DeployStore } from '../../state/deploy.store';
import type { DraftRow } from './deploy-steps-editor.types';
import { NO_PROBLEMS, draftOf, draftProblems, emptyDraft, hasProblems, stepOf } from './step-drafts';
import type { DraftPatch, DraftStep } from './step-drafts.types';

@Component({
  selector: 'app-deploy-steps-editor',
  imports: [
    FormsModule,
    MatButton,
    MatIconButton,
    MatCheckbox,
    MatChipGrid,
    MatChipInput,
    MatChipRemove,
    MatChipRow,
    MatError,
    MatFormField,
    MatHint,
    MatInput,
    MatLabel,
    MatMenu,
    MatMenuItem,
    MatMenuTrigger,
    FieldError,
    Notice,
    TranslatePipe,
  ],
  templateUrl: './deploy-steps-editor.html',
  styleUrl: './deploy-steps-editor.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DeployStepsEditor {
  private readonly store = inject(DeployStore);
  private readonly dialogs = inject(Dialogs);
  private readonly locale = inject(LocaleStore);

  readonly application = input.required<DeployApplication>();
  readonly closed = output();

  protected readonly separators = [ENTER, COMMA];
  protected readonly timeoutMin = DEPLOY_TIMEOUT_MIN;
  protected readonly timeoutMax = DEPLOY_TIMEOUT_MAX;

  // Only the rows' identity for `track`; never on screen.
  private nextKey = 0;

  readonly drafts = linkedSignal<readonly DraftStep[]>(() =>
    this.application().deploy_steps.map((step) => draftOf(step, this.newKey())),
  );

  private readonly submitted = signal(false);

  readonly saving = this.store.saving;

  readonly kinds = computed(() => kindsFor(this.application()));

  readonly full = computed(() => this.drafts().length >= DEPLOY_STEPS_MAX);

  readonly folderMissing = computed(() => this.application().project_dir === '');

  readonly listMessages = computed(() => this.store.listErrors().map((code) => this.problemText(code)));

  readonly rows = computed<readonly DraftRow[]>(() => {
    const application = this.application();
    const refused = this.store.stepErrors();
    const submitted = this.submitted();
    const drafts = this.drafts();
    return drafts.map((draft, index) => {
      const fit = fitProblems(draft.kind, application);
      const server = (refused.get(index) ?? []).filter((code) => !(fit as readonly string[]).includes(code));
      return {
        draft,
        position: index + 1,
        first: index === 0,
        last: index === drafts.length - 1,
        services: takesServices(draft.kind),
        fields: submitted ? draftProblems(draft) : NO_PROBLEMS,
        messages: [...fit, ...server].map((code) => this.problemText(code)),
      };
    });
  });

  private readonly invalid = computed(() => {
    const application = this.application();
    return this.drafts().some(
      (draft) => hasProblems(draftProblems(draft)) || fitProblems(draft.kind, application).length > 0,
    );
  });

  add(kind: DeployStepKind): void {
    if (this.full()) {
      return;
    }
    this.drafts.update((drafts) => [...drafts, emptyDraft(kind, this.newKey())]);
    this.store.clearSaveError();
  }

  remove(index: number): void {
    this.drafts.update((drafts) => drafts.filter((_, at) => at !== index));
    this.store.clearSaveError();
  }

  moveUp(index: number): void {
    this.swap(index - 1, index);
  }

  moveDown(index: number): void {
    this.swap(index, index + 1);
  }

  update(index: number, patch: DraftPatch): void {
    this.drafts.update((drafts) => drafts.map((draft, at) => (at === index ? { ...draft, ...patch } : draft)));
    this.store.clearSaveError();
  }

  addService(index: number, event: MatChipInputEvent): void {
    const name = event.value.trim();
    event.chipInput.clear();
    const draft = this.drafts()[index];
    if (name === '' || draft === undefined || draft.services.includes(name)) {
      return;
    }
    this.update(index, { services: [...draft.services, name] });
  }

  removeService(index: number, name: string): void {
    const draft = this.drafts()[index];
    if (draft !== undefined) {
      this.update(index, { services: draft.services.filter((service) => service !== name) });
    }
  }

  async save(): Promise<void> {
    this.submitted.set(true);
    if (this.invalid() || this.saving()) {
      return;
    }
    const steps = this.drafts().map(stepOf);
    const data: PasswordPromptData = {
      titleKey: 'redeploy.editor.prompt.title',
      bodyKey: 'redeploy.editor.prompt.body',
      submitKey: 'redeploy.editor.save',
      submit: async (password) => (await this.store.saveSteps(steps, password)) || this.store.stepsRefused(),
      error: this.store.saveError,
    };
    const answered = await this.dialogs
      .open<boolean, PasswordPromptData>(PasswordPrompt, { titleKey: data.titleKey, data, size: 'sm' })
      .whenClosed();
    if (answered === true && this.store.saveError() === null) {
      this.closed.emit();
    }
  }

  cancel(): void {
    this.store.clearSaveError();
    this.closed.emit();
  }

  private swap(first: number, second: number): void {
    const drafts = [...this.drafts()];
    if (first < 0 || second >= drafts.length) {
      return;
    }
    [drafts[first], drafts[second]] = [drafts[second], drafts[first]];
    this.drafts.set(drafts);
    this.store.clearSaveError();
  }

  private problemText(code: string): string {
    return isStepProblem(code) ? this.locale.translate(`redeploy.problems.${code}`) : errorText(this.locale, code);
  }

  private newKey(): number {
    this.nextKey += 1;
    return this.nextKey;
  }
}
