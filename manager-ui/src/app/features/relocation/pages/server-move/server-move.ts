import { ChangeDetectionStrategy, Component, afterRenderEffect, computed, effect, inject, linkedSignal, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { MatButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { MatCheckbox } from '@angular/material/checkbox';
import { MatError, MatFormField, MatHint, MatLabel } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';
import { MatRadioButton, MatRadioGroup } from '@angular/material/radio';
import { MatStep, MatStepper, MatStepperIcon } from '@angular/material/stepper';

import { Can } from '@core/auth/directives/can';
import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { routeParam } from '@core/routing/route-param';
import { ConfirmedRun } from '@shared/confirmed-run/confirmed-run';
import type { RunRequest } from '@shared/confirmed-run/confirmed-run.types';
import { FieldError } from '@shared/field/field-error';
import { Notice } from '@shared/notice/notice';
import { PasswordInput } from '@shared/password-input/password-input';
import { MovePlan } from '../../components/move-plan/move-plan';
import { MoveProgress } from '../../components/move-progress/move-progress';
import { movedName } from '../../data/moved-name';
import type { ChoiceDraft, MoveChoice } from '../../data/relocation.types';
import { ServerMoveStore } from '../../state/server-move.store';
import type { DraftSource, MoveWizardStep } from './server-move.types';

const STEPS: readonly MoveWizardStep[] = ['target', 'applications', 'plan', 'confirm', 'progress'];

const ABSOLUTE_PATH = /^\/(?!.*(?:^|\/)\.\.(?:\/|$))/;

@Component({
  selector: 'app-server-move',
  imports: [
    Can,
    FormsModule,
    RouterLink,
    MatButton,
    MatCard,
    MatCardContent,
    MatCheckbox,
    MatError,
    MatFormField,
    MatHint,
    MatInput,
    MatLabel,
    MatRadioButton,
    MatRadioGroup,
    MatStep,
    MatStepper,
    MatStepperIcon,
    ConfirmedRun,
    FieldError,
    MovePlan,
    MoveProgress,
    Notice,
    PasswordInput,
    ErrorTextPipe,
    TranslatePipe,
  ],
  templateUrl: './server-move.html',
  styleUrl: './server-move.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ServerMovePage {
  private readonly store = inject(ServerMoveStore);
  private readonly route = inject(ActivatedRoute);

  readonly serverId = routeParam(this.route, 'serverId');
  readonly steps = STEPS;

  readonly step = signal(0);
  protected readonly shownStep = signal(0);
  private readonly attempted = signal<ReadonlySet<MoveWizardStep>>(new Set());

  readonly source = this.store.source;
  readonly targets = this.store.targets;
  readonly loadError = this.store.loadError;
  readonly planning = this.store.planning;
  readonly moving = this.store.moving;
  readonly plan = this.store.plan;
  readonly planned = this.store.planned;
  readonly planBlocked = this.store.planBlocked;
  readonly progress = this.store.progress;

  readonly target = signal<string | null>(this.route.snapshot.queryParamMap.get('target'));
  readonly targetServer = computed(() => this.targets().find((server) => server.id === this.target()) ?? null);
  readonly targetName = computed(() => this.targetServer()?.name ?? '');
  readonly drafts = linkedSignal<DraftSource, readonly ChoiceDraft[]>({
    source: () => ({ applications: this.store.applications(), target: this.targetName() }),
    computation: ({ applications, target }, previous) =>
      applications.map((application) => {
        const name = movedName(application.name, target);
        const before = previous?.value.find((draft) => draft.application.id === application.id);
        if (!before) {
          return { application, selected: true, name, folder: application.project_dir };
        }
        const untouched = before.name === movedName(application.name, previous?.source.target ?? '');
        return { ...before, application, name: untouched ? name : before.name };
      }),
  });
  readonly copyPlans = signal(true);
  readonly sudoPassword = signal('');
  readonly sourceSudoPassword = signal('');
  readonly resumeOf = signal<number | null>(null);

  readonly choices = computed<readonly MoveChoice[]>(() =>
    this.drafts()
      .filter((draft) => draft.selected)
      .map((draft) => ({
        application: draft.application.id,
        name: draft.name.trim(),
        folder: draft.folder.trim(),
        skip_volumes: [],
        copy_plans: this.copyPlans(),
      })),
  );
  readonly needsSudo = computed(() => this.plan()?.inventory?.needs_sudo ?? { target: false, source: false });
  readonly moveJob = this.moving.job;
  readonly moved = computed(() => this.moveJob()?.status === 'succeeded');
  readonly stopped = computed(() => this.moveJob()?.status === 'failed');
  readonly created = computed(() => this.progress()?.created ?? []);
  readonly leftovers = computed(() => this.progress()?.leftovers ?? []);
  readonly started = computed(() => this.moveJob() !== null || this.moving.busy());

  constructor() {
    effect(() => this.store.open(this.serverId()));
    afterRenderEffect({ write: () => this.shownStep.set(this.step()) });
  }

  stepDone(step: MoveWizardStep): boolean {
    return STEPS.indexOf(step) < this.step() && this.stepReady(step);
  }

  shown(step: MoveWizardStep): boolean {
    return this.attempted().has(step);
  }

  nameError(draft: ChoiceDraft): string {
    return this.shown('applications') && draft.selected && draft.name.trim() === '' ? 'relocation.applications.nameRequired' : '';
  }

  folderError(draft: ChoiceDraft): string {
    const folder = draft.folder.trim();
    return this.shown('applications') && draft.selected && folder !== '' && !ABSOLUTE_PATH.test(folder)
      ? 'absolute_path_required'
      : '';
  }

  update(index: number, change: Partial<ChoiceDraft>): void {
    this.drafts.update((drafts) => drafts.map((draft, position) => (position === index ? { ...draft, ...change } : draft)));
  }

  back(): void {
    this.step.update((step) => Math.max(0, step - 1));
  }

  advance(): void {
    const step = STEPS[this.step()];
    this.attempted.update((attempted) => new Set(attempted).add(step));
    if (!this.stepReady(step)) {
      return;
    }
    this.step.update((index) => Math.min(index + 1, STEPS.length - 1));
    if (STEPS[this.step()] === 'plan') {
      this.rehearse();
    }
  }

  rehearse(): void {
    const target = this.target();
    if (target) {
      this.store.rehearse(target, this.choices());
    }
  }

  run(request: RunRequest): void {
    const target = this.target();
    if (!target) {
      return;
    }
    if (request.rehearsal) {
      this.step.set(STEPS.indexOf('plan'));
      this.rehearse();
      return;
    }
    this.store.move(target, this.choices(), request, this.sudoPassword(), this.sourceSudoPassword(), this.resumeOf());
    this.sudoPassword.set('');
    this.sourceSudoPassword.set('');
    this.step.set(STEPS.indexOf('progress'));
  }

  resume(): void {
    const job = this.moveJob();
    if (!job) {
      return;
    }
    this.resumeOf.set(job.id);
    this.moving.forget();
    this.step.set(STEPS.indexOf('confirm'));
  }

  private stepReady(step: MoveWizardStep): boolean {
    switch (step) {
      case 'target':
        return this.targetServer() !== null;
      case 'applications':
        return (
          this.choices().length > 0 &&
          this.drafts().every((draft) => this.nameErrorFor(draft) === '' && this.folderErrorFor(draft) === '')
        );
      case 'plan':
        return this.planned();
      case 'confirm':
        return this.started();
      case 'progress':
        return this.moved();
    }
  }

  private nameErrorFor(draft: ChoiceDraft): string {
    return draft.selected && draft.name.trim() === '' ? 'required' : '';
  }

  private folderErrorFor(draft: ChoiceDraft): string {
    const folder = draft.folder.trim();
    return draft.selected && folder !== '' && !ABSOLUTE_PATH.test(folder) ? 'absolute_path_required' : '';
  }
}
