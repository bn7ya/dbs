import { ChangeDetectionStrategy, Component, afterRenderEffect, computed, effect, inject, signal, type Signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { MatButton, MatIconButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { MatError, MatFormField, MatHint, MatLabel, MatSuffix } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';
import { MatRadioButton, MatRadioGroup } from '@angular/material/radio';
import { MatStep, MatStepper, MatStepperIcon } from '@angular/material/stepper';

import type { ApiError } from '@core/http/api.types';
import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { isFinished } from '@core/jobs/job.types';
import { routeParam } from '@core/routing/route-param';
import { Dialogs } from '@shared/dialogs/dialogs';
import { FieldError } from '@shared/field/field-error';
import { isolated } from '@shared/isolated/isolated';
import { JobConnection } from '@shared/job-connection/job-connection';
import { Notice } from '@shared/notice/notice';
import { PasswordPrompt } from '@shared/password-prompt/password-prompt';
import type { PasswordPromptData } from '@shared/password-prompt/password-prompt.types';
import { uniqueId } from '@shared/unique-id';
import { CandidateFacts } from '../../components/candidate-facts/candidate-facts';
import { CheckReport } from '../../components/check-report/check-report';
import { browseServer } from '../../components/server-browser/browse-server';
import type { BrowsedField } from '../../components/server-browser/server-browser.types';
import {
  BLANK_DRAFT,
  DETAIL_FIELDS,
  draftFromCandidate,
  draftFromFolder,
  draftProblems,
  settingsOf,
} from '../../components/settings-fields/application-draft';
import { SettingsFields } from '../../components/settings-fields/settings-fields';
import type { ApplicationDraft, DraftErrors, DraftField } from '../../components/settings-fields/settings-fields.types';
import { WhereItRuns } from '../../components/where-it-runs/where-it-runs';
import { ApplicationWizardStore } from '../../state/application-wizard.store';
import type { WizardField, WizardStep } from './application-wizard.types';

const STEPS: readonly WizardStep[] = ['folder', 'discovery', 'review', 'check', 'passphrase', 'backup'];

const FIRST_AFTER_CREATION = STEPS.indexOf('check');

const ABSOLUTE_PATH = /^\//;

@Component({
  selector: 'app-application-wizard',
  imports: [
    FormsModule,
    RouterLink,
    MatButton,
    MatIconButton,
    MatCard,
    MatCardContent,
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
    MatSuffix,
    CandidateFacts,
    CheckReport,
    FieldError,
    JobConnection,
    Notice,
    SettingsFields,
    WhereItRuns,
    ErrorTextPipe,
    TranslatePipe,
  ],
  providers: [Dialogs],
  templateUrl: './application-wizard.html',
  styleUrl: './application-wizard.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ApplicationWizardPage {
  private readonly store = inject(ApplicationWizardStore);
  private readonly dialogs = inject(Dialogs);

  readonly serverId = routeParam(inject(ActivatedRoute), 'serverId');

  readonly steps = STEPS;
  readonly firstAfterCreation = FIRST_AFTER_CREATION;
  readonly reviewStep = STEPS.indexOf('review');
  protected readonly detailsId = uniqueId('application-details');

  readonly step = signal(0);
  protected readonly shownStep = signal(0);
  private readonly attempted = signal<ReadonlySet<WizardStep>>(new Set());

  readonly folder = signal('');
  private readonly discoveredFolder = signal<string | null>(null);
  readonly chosen = signal<number | null>(null);
  readonly draft = signal<ApplicationDraft>(BLANK_DRAFT);
  private readonly draftFrom = signal<string | null>(null);
  private readonly edited = signal<ReadonlySet<DraftField>>(new Set());
  private readonly detailsShown = signal(false);

  readonly server = this.store.server;
  readonly serverError = this.store.serverError;
  readonly discovery = this.store.discovery;
  readonly application = this.store.application;
  readonly versions = this.store.versions;
  readonly captured = this.store.captured;
  readonly backupJob = this.store.backupJob;

  readonly discovering = this.store.discovering;
  readonly discoverError = computed(() => withoutPasswordAsk(this.store.discoverError()));
  readonly creating = this.store.creating;
  readonly createFailure = computed(() => {
    const failure = this.store.createError();
    return failure && !failure.fields ? failure : null;
  });
  readonly saving = this.store.saving;
  readonly saveFailure = computed(() => withoutPasswordAsk(this.store.saveError()));
  readonly checking = this.store.checking;
  readonly checkError = this.store.checkError;
  readonly capturing = this.store.capturing;
  readonly captureError = this.store.captureError;
  readonly backingUp = this.store.backingUp;
  readonly backupError = this.store.backupError;

  readonly created = computed(() => this.application() !== null);
  readonly busy = computed(() => this.discovering() || this.creating() || this.checking() || this.saving());

  readonly matched = computed(() => this.discovery()?.listing.manage !== undefined);
  readonly candidates = computed(() => this.discovery()?.candidates ?? []);
  readonly candidate = computed(() => {
    const index = this.chosen();
    return index === null ? null : (this.candidates()[index] ?? null);
  });
  readonly pythonPaths = computed(() => this.candidate()?.python_paths ?? []);
  readonly envCandidates = computed(() => this.candidate()?.env ?? []);
  readonly searchedFolder = computed(() => isolated(this.discovery()?.folder ?? ''));

  readonly passed = computed(() => this.versions()?.compatible === true);
  readonly reported = computed(() => {
    const status = this.application()?.last_check_status;
    return status === 'ok' || status === 'problem';
  });
  readonly lastCheckError = computed(() => {
    const application = this.application();
    return application?.last_check_status === 'failed' ? application.last_check_error : '';
  });
  readonly suggestion = computed(() => this.application()?.last_check_report.python_suggestion ?? null);
  readonly backedUp = computed(() => this.backupJob()?.status === 'succeeded');
  readonly backupRunning = computed(() => {
    const job = this.backupJob();
    return job !== null && !isFinished(job);
  });

  private readonly problems = computed<ReadonlyMap<WizardField, string>>(() => {
    const problems = new Map<WizardField, string>(draftProblems(this.draft()));
    const folder = this.folder().trim();
    if (folder !== '' && !ABSOLUTE_PATH.test(folder)) {
      problems.set('folder', 'absolute_path_required');
    }
    return problems;
  });

  readonly errors = computed<DraftErrors>(() => {
    const shown: Partial<Record<DraftField, string>> = {};
    for (const field of Object.keys(BLANK_DRAFT) as DraftField[]) {
      const code = this.error(field);
      if (code !== null) {
        shown[field] = code;
      }
    }
    return shown;
  });

  readonly detailsOpen = computed(() => this.detailsShown() || DETAIL_FIELDS.some((field) => field in this.errors()));

  constructor() {
    effect(() => this.store.open(this.serverId()));
    afterRenderEffect({ write: () => this.shownStep.set(this.step()) });
  }

  error(field: WizardField): string | null {
    const step: WizardStep = field === 'folder' ? 'folder' : 'review';
    const own = this.attempted().has(step) ? this.problems().get(field) : undefined;
    if (own) {
      return own;
    }
    if (field === 'folder') {
      return this.store.discoverError()?.fields?.['folder']?.[0] ?? null;
    }
    return this.edited().has(field) ? null : (this.store.createError()?.fields?.[field]?.[0] ?? null);
  }

  stepDone(step: WizardStep): boolean {
    return STEPS.indexOf(step) < this.step() && this.stepReady(step);
  }

  update<K extends keyof ApplicationDraft>(field: K, value: ApplicationDraft[K]): void {
    this.changeDraft({ [field]: value });
  }

  changeDraft(change: Partial<ApplicationDraft>): void {
    this.draft.update((draft) => ({ ...draft, ...change }));
    this.edited.update((edited) => new Set([...edited, ...(Object.keys(change) as DraftField[])]));
  }

  toggleDetails(): void {
    this.detailsShown.update((shown) => !shown);
  }

  choose(index: number | null): void {
    this.chosen.set(index);
  }

  pickFolder(path: string): void {
    this.folder.set(path);
    void this.discover();
  }

  async browseFolder(): Promise<void> {
    const server = this.serverId();
    if (!server) {
      return;
    }
    const paths = { project_dir: this.folder(), remote_backup_dir: '', env_path: '' };
    const picked = await browseServer(this.dialogs, server, 'folder', paths, this.discovery()?.folders ?? []);
    if (picked) {
      this.folder.set(picked);
      if (STEPS[this.step()] === 'discovery') {
        await this.discover();
      }
    }
  }

  async browse(field: BrowsedField): Promise<void> {
    const server = this.serverId();
    if (!server) {
      return;
    }
    const picked = await browseServer(this.dialogs, server, field, this.draft(), this.discovery()?.folders ?? []);
    if (!picked) {
      return;
    }
    if (field === 'file_roots') {
      const roots = this.draft().file_roots;
      if (!roots.includes(picked)) {
        this.update('file_roots', [...roots, picked]);
      }
    } else if (field !== 'folder') {
      this.update(field, picked);
    }
  }

  async discover(): Promise<void> {
    const folder = this.folder().trim();
    const found = await this.withPassword((password) => this.store.discover(folder, password), this.store.discoverError);
    if (found) {
      this.discoveredFolder.set(folder);
      this.chosen.set(found.candidates.length > 0 ? 0 : null);
    }
  }

  async useSuggestedPython(): Promise<void> {
    const suggestion = this.suggestion();
    if (!suggestion) {
      return;
    }
    const saved = await this.withPassword(
      (password) =>
        this.store.update({ python_path: suggestion.python_path, ...(password ? { account_password: password } : {}) }),
      this.store.saveError,
      'applications.wizard.password.running',
    );
    if (saved) {
      this.update('python_path', suggestion.python_path);
      await this.store.check();
    }
  }

  checkAgain(): void {
    void this.store.check();
  }

  capturePassphrase(): void {
    void this.store.capturePassphrase();
  }

  takeBackup(): void {
    this.store.takeBackup();
  }

  back(): void {
    this.step.update((step) => Math.max(this.created() ? FIRST_AFTER_CREATION : 0, step - 1));
  }

  async advance(): Promise<void> {
    if (this.busy()) {
      return;
    }
    const step = STEPS[this.step()];
    this.attempted.update((attempted) => new Set(attempted).add(step));
    if (!this.stepReady(step)) {
      if (step === 'discovery') {
        await this.discover();
      } else if (step === 'check') {
        await this.store.check();
      }
      return;
    }
    if (step === 'discovery') {
      this.prepareDraft();
    } else if (step === 'review' && !(await this.createOnce())) {
      return;
    }
    this.step.update((index) => Math.min(index + 1, STEPS.length - 1));
    this.arrive(STEPS[this.step()]);
  }

  private stepReady(step: WizardStep): boolean {
    switch (step) {
      case 'folder':
        return !this.problems().has('folder');
      case 'discovery':
        return this.discovery() !== null && !this.discovering();
      case 'review':
        return [...this.problems().keys()].every((field) => field === 'folder');
      case 'check':
        return this.passed();
      case 'passphrase':
        return true;
      case 'backup':
        return this.backedUp();
    }
  }

  private arrive(step: WizardStep): void {
    if (step === 'discovery' && (this.discovery() === null || this.discoveredFolder() !== this.folder().trim())) {
      void this.discover();
    } else if (step === 'check') {
      void this.store.check();
    }
  }

  private prepareDraft(): void {
    const source = `${this.discoveredFolder()}\n${this.chosen()}`;
    if (this.draftFrom() === source) {
      return;
    }
    const candidate = this.candidate();
    this.draft.set(candidate ? draftFromCandidate(candidate) : draftFromFolder(this.discovery()?.folder || this.folder().trim()));
    this.edited.set(new Set());
    this.draftFrom.set(source);
  }

  private async createOnce(): Promise<boolean> {
    if (this.created()) {
      return true;
    }
    this.edited.set(new Set());
    const settings = { ...settingsOf(this.draft()), discovered: this.candidate() !== null };
    const created = await this.withPassword(
      (password) => this.store.create({ ...settings, ...(password ? { account_password: password } : {}) }),
      this.store.createError,
      'applications.wizard.password.adding',
    );
    return created !== null;
  }

  private async withPassword<T>(
    attempt: (password?: string) => Promise<T | null>,
    failure: Signal<ApiError | null>,
    bodyKey = 'applications.wizard.password.body',
  ): Promise<T | null> {
    const first = await attempt();
    if (first !== null || !asksForPassword(failure())) {
      return first;
    }
    let answer: T | null = null;
    const data: PasswordPromptData = {
      titleKey: 'applications.wizard.password.title',
      bodyKey,
      submitKey: 'applications.wizard.password.submit',
      submit: async (password) => {
        answer = await attempt(password);
        return answer !== null;
      },
      error: failure,
    };
    await this.dialogs
      .open<boolean, PasswordPromptData>(PasswordPrompt, { titleKey: data.titleKey, data, size: 'sm' })
      .whenClosed();
    return answer;
  }
}

function asksForPassword(error: ApiError | null): boolean {
  return (error?.fields?.['account_password'] ?? []).length > 0;
}

function withoutPasswordAsk(error: ApiError | null): ApiError | null {
  return asksForPassword(error) ? null : error;
}
