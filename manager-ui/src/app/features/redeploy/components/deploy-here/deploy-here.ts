import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { MatButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';

import { Can } from '@core/auth/directives/can';
import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { EmptyState } from '@shared/empty-state/empty-state';
import { isolated } from '@shared/isolated/isolated';
import { Notice } from '@shared/notice/notice';
import { Skeleton } from '@shared/skeleton/skeleton';
import { uniqueId } from '@shared/unique-id';
import { fitProblems, takesServices } from '../../data/deploy-catalogue';
import type { RunRequest } from '@shared/confirmed-run/confirmed-run.types';
import type { DeployStep, Revisions } from '../../data/redeploy.types';
import { DeployStore } from '../../state/deploy.store';
import { ConfirmedRun } from '@shared/confirmed-run/confirmed-run';
import { DeployStepsEditor } from '../deploy-steps-editor/deploy-steps-editor';
import { JobProgress } from '../job-progress/job-progress';
import { RevertPanel } from '../revert-panel/revert-panel';
import type { RevisionRow, SavedStepRow } from './deploy-here.types';

const REVISION_KINDS: readonly (keyof Revisions)[] = ['git_head', 'image'];

const STEPS_FIELD = /^steps(\.\d+)?$/;

@Component({
  selector: 'app-deploy-here',
  imports: [
    Can,
    MatButton,
    MatCard,
    MatCardContent,
    ConfirmedRun,
    DeployStepsEditor,
    EmptyState,
    JobProgress,
    Notice,
    RevertPanel,
    Skeleton,
    ErrorTextPipe,
    TranslatePipe,
  ],
  templateUrl: './deploy-here.html',
  styleUrl: './deploy-here.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DeployHere {
  readonly headingId = uniqueId('deploy-title');

  private readonly store = inject(DeployStore);
  private readonly locale = inject(LocaleStore);

  readonly application = this.store.application;
  readonly loadError = this.store.loadError;
  readonly deploying = this.store.deploying;
  readonly reverting = this.store.reverting;
  readonly outcome = this.store.outcome;

  readonly editing = signal(false);

  readonly savedSteps = computed<readonly SavedStepRow[]>(() => {
    const application = this.application();
    if (application === null) {
      return [];
    }
    return application.deploy_steps.map((step, index) => ({
      position: index + 1,
      label: this.locale.translate(`redeploy.deploy.steps.${step.kind}`),
      details: [
        ...this.detailsOf(step),
        this.locale.translate('redeploy.deploy.list.timeLimit', { minutes: step.timeout_minutes }),
      ],
      problems: fitProblems(step.kind, application).map((code) => this.locale.translate(`redeploy.problems.${code}`)),
    }));
  });

  readonly stepsInvalid = computed(() =>
    Object.keys(this.deploying.error()?.fields ?? {}).some((field) => STEPS_FIELD.test(field)),
  );

  readonly runError = computed(() => (this.stepsInvalid() ? null : this.deploying.error()));

  readonly revisions = computed<readonly RevisionRow[]>(() => {
    const { before, after } = this.outcome();
    return REVISION_KINDS.filter((kind) => before[kind] !== undefined || after[kind] !== undefined).map((kind) => ({
      kind,
      before: before[kind] ?? null,
      after: after[kind] ?? null,
    }));
  });

  edit(): void {
    this.store.clearSaveError();
    this.editing.set(true);
  }

  closeEditor(): void {
    this.editing.set(false);
  }

  deploy(request: RunRequest): void {
    this.store.deploy(request);
  }

  restore(request: RunRequest): void {
    this.store.revert(request);
  }

  clearRunError(): void {
    this.deploying.clearError();
  }

  clearRevertError(): void {
    this.reverting.clearError();
  }

  retry(): void {
    this.store.reload();
  }

  private detailsOf(step: DeployStep): readonly string[] {
    const options = step.options;
    const details: string[] = [];
    if (step.kind === 'git_pull') {
      details.push(this.pullFrom(options.remote ?? '', options.branch ?? ''));
    }
    if (takesServices(step.kind)) {
      const services = options.services ?? [];
      details.push(
        services.length === 0
          ? this.locale.translate('redeploy.deploy.list.everyService')
          : this.locale.translate('redeploy.deploy.list.services', { services: this.listed(services) }),
      );
    }
    if (step.kind === 'compose_build' && options.pull === true) {
      details.push(this.locale.translate('redeploy.deploy.list.pullBase'));
    }
    if (step.kind === 'systemd_user_restart' && options.unit) {
      details.push(this.locale.translate('redeploy.deploy.list.unit', { unit: isolated(options.unit) }));
    }
    if (step.kind === 'pip_install' && options.requirements) {
      details.push(this.locale.translate('redeploy.deploy.list.requirements', { file: isolated(options.requirements) }));
    }
    return details;
  }

  private pullFrom(remote: string, branch: string): string {
    if (remote !== '' && branch !== '') {
      return this.locale.translate('redeploy.deploy.list.remoteBranch', {
        remote: isolated(remote),
        branch: isolated(branch),
      });
    }
    if (branch !== '') {
      return this.locale.translate('redeploy.deploy.list.branch', { branch: isolated(branch) });
    }
    return this.locale.translate('redeploy.deploy.list.upstream');
  }

  private listed(names: readonly string[]): string {
    return new Intl.ListFormat(this.locale.locale(), { type: 'conjunction' }).format(names.map(isolated));
  }
}
