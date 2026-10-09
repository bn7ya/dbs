import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonDirective } from 'primeng/button';
import { InputNumber } from 'primeng/inputnumber';
import { InputTags } from 'primeng/inputtags';
import { InputText } from 'primeng/inputtext';
import { Message } from 'primeng/message';
import { RadioButton } from 'primeng/radiobutton';
import { Select } from 'primeng/select';
import { ToggleSwitch } from 'primeng/toggleswitch';

import { ErrorTextPipe, errorText } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { injectDialogData, injectDialogRef } from '@shared/dialogs/dialogs';
import { Field } from '@shared/field/field';
import { FieldControl } from '@shared/field/field-control';
import { PasswordInput } from '@shared/password-input/password-input';
import { uniqueId } from '@shared/unique-id';
import { PLAN_SCHEDULES, scheduleOf, type BackupKind, type BackupPlan, type PlanSchedule, type PlanSettings } from '../../data/backups.types';
import { BackupsStore } from '../../state/backups.store';
import type { Draft, DraftField, PlanFormData, ScheduleOption } from './plan-form.types';

const FIELD_OF: Readonly<Record<keyof Draft, DraftField>> = {
  kind: 'kind',
  paths: 'paths',
  folder: 'paths',
  pattern: 'pattern',
  name: 'name',
  schedule: 'interval_minutes',
  keep: 'keep',
  keep_remote: 'keep_remote',
  enabled: 'enabled',
};

const KEEP_MAX = 365;
const KEEP_MIN = 1;
const KEEP_REMOTE_MIN = 0;

const NEW_PLAN: Draft = {
  kind: 'dbs',
  paths: [],
  folder: '',
  pattern: '*',
  name: '',
  schedule: 'daily',
  keep: 7,
  keep_remote: 1,
  enabled: true,
};

const SCHEDULES = Object.keys(PLAN_SCHEDULES) as PlanSchedule[];

const KINDS: readonly BackupKind[] = ['dbs', 'archive', 'collect'];

@Component({
  selector: 'app-plan-form',
  imports: [
    FormsModule,
    ButtonDirective,
    InputNumber,
    InputTags,
    InputText,
    Message,
    PasswordInput,
    RadioButton,
    Select,
    ToggleSwitch,
    Field,
    FieldControl,
    ErrorTextPipe,
    TranslatePipe,
  ],
  templateUrl: './plan-form.html',
  styleUrl: './plan-form.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PlanForm {
  private readonly store = inject(BackupsStore);
  private readonly ref = injectDialogRef<BackupPlan>();
  private readonly locale = inject(LocaleStore);
  private readonly data = injectDialogData<PlanFormData>();

  readonly editing = this.data.plan;

  readonly kindId = uniqueId('plan-kind');
  readonly kinds = KINDS;

  readonly keepMin = KEEP_MIN;
  readonly keepRemoteMin = KEEP_REMOTE_MIN;
  readonly keepMax = KEEP_MAX;

  readonly draft = signal<Draft>(
    this.editing
      ? draftOf(this.editing)
      : { ...NEW_PLAN, name: this.data.name ?? NEW_PLAN.name, kind: this.data.kind ?? NEW_PLAN.kind },
  );

  readonly archiving = computed(() => this.draft().kind === 'archive');

  readonly collecting = computed(() => this.draft().kind === 'collect');

  readonly saving = this.store.savingPlan;
  readonly saveError = this.store.planSaveError;

  readonly scheduleOptions = computed<ScheduleOption[]>(() =>
    SCHEDULES.map((schedule) => ({ value: schedule, label: this.locale.translate(`backups.schedule.${schedule}`) })),
  );

  private readonly attempted = signal(false);

  private readonly edited = signal<ReadonlySet<DraftField>>(new Set());

  private readonly problems = computed(() => problemsIn(this.draft()));

  // The reader's own mistake first, then the backend's, unless the field changed since.
  private readonly shown = computed(() => {
    const shown = new Map<string, string>(this.attempted() ? this.problems() : []);
    const edited = this.edited();
    for (const [field, codes] of Object.entries(this.saveError()?.fields ?? {})) {
      if (!shown.has(field) && !edited.has(field as DraftField) && codes.length > 0) {
        shown.set(field, codes[0]);
      }
    }
    return shown;
  });

  readonly accountPassword = signal('');

  private readonly passwordEdited = signal(false);

  readonly needsPassword = computed(() => {
    const draft = this.draft();
    return draft.kind !== 'dbs' && (this.editing === null || readsElsewhere(draftOf(this.editing), draft));
  });

  private readonly passwordAsked = computed(() => (this.saveError()?.fields?.['account_password'] ?? []).length > 0);

  readonly passwordShown = computed(() => this.needsPassword() || this.passwordAsked());

  readonly passwordMissing = computed(
    () =>
      this.accountPassword() === '' &&
      ((this.attempted() && this.needsPassword()) || (this.passwordAsked() && !this.passwordEdited())),
  );

  readonly passwordRejected = computed(() => this.saveError()?.code === 'invalid_password' && !this.passwordEdited());

  readonly passwordError = computed(() => {
    if (this.passwordMissing()) {
      return this.locale.translate('password.required');
    }
    return this.passwordRejected() ? errorText(this.locale, 'invalid_password') : '';
  });

  readonly formFailure = computed(() => {
    const failure = this.saveError();
    return failure && failure.code !== 'invalid_password' ? failure : null;
  });

  // A django-dbs plan has no folder field, so what the backend says about its folders is said here.
  readonly kindError = computed(
    () => this.error('kind') ?? (this.draft().kind === 'dbs' ? this.error('paths') : null),
  );

  constructor() {
    this.store.resetPlanForm();
  }

  error(field: DraftField): string | null {
    return this.shown().get(field) ?? null;
  }

  errorFor(field: DraftField): string {
    const code = this.error(field);
    return code === null ? '' : errorText(this.locale, code);
  }

  update<K extends keyof Draft>(field: K, value: Draft[K]): void {
    this.draft.update((draft) => ({ ...draft, [field]: value }));
    this.edited.update((edited) => new Set(edited).add(FIELD_OF[field]));
  }

  // Another kind sends other folders, pattern and copies on the server, so their errors no longer hold.
  setKind(kind: BackupKind | null): void {
    if (kind) {
      this.update('kind', kind);
      this.edited.update((edited) => new Set<DraftField>([...edited, 'paths', 'pattern', 'keep_remote']));
    }
  }

  setAccountPassword(password: string): void {
    this.accountPassword.set(password);
    this.passwordEdited.set(true);
  }

  setSchedule(value: PlanSchedule | null): void {
    if (value !== null) {
      this.update('schedule', value);
    }
  }

  cancel(): void {
    this.ref.close();
  }

  async save(): Promise<void> {
    this.attempted.set(true);
    const draft = this.draft();
    const settings = settingsOf(draft);
    if (this.problems().size > 0 || settings === null || this.passwordMissing()) {
      return;
    }
    this.edited.set(new Set());
    this.passwordEdited.set(false);
    const password = this.passwordShown() && this.accountPassword() ? { account_password: this.accountPassword() } : {};
    const saved = this.editing
      ? await this.store.updatePlan(this.editing, settings, password)
      : await this.store.createPlan(draft.kind, settings, password);
    if (saved) {
      this.ref.close(saved);
    }
  }
}

function problemsIn(draft: Draft): ReadonlyMap<DraftField, string> {
  const problems = new Map<DraftField, string>();
  if (draft.kind === 'archive') {
    if (draft.paths.length === 0) {
      problems.set('paths', 'paths_required');
    } else if (!draft.paths.every(isAbsolutePath)) {
      problems.set('paths', 'absolute_path_required');
    }
  }
  if (draft.kind === 'collect') {
    if (draft.folder.trim() === '') {
      problems.set('paths', 'required');
    } else if (!isAbsolutePath(draft.folder)) {
      problems.set('paths', 'absolute_path_required');
    }
    if (draft.pattern.trim() === '') {
      problems.set('pattern', 'required');
    } else if (draft.pattern.includes('/')) {
      problems.set('pattern', 'invalid_pattern');
    }
  }
  if (draft.name.trim() === '') {
    problems.set('name', 'required');
  }
  if (draft.keep === null) {
    problems.set('keep', 'required');
  } else if (!inRange(draft.keep, KEEP_MIN)) {
    problems.set('keep', 'keep_range');
  }
  if (draft.kind === 'collect') {
    return problems;
  }
  if (draft.keep_remote === null) {
    problems.set('keep_remote', 'required');
  } else if (!inRange(draft.keep_remote, KEEP_REMOTE_MIN)) {
    problems.set('keep_remote', 'keep_remote_range');
  }
  return problems;
}

function isAbsolutePath(path: string): boolean {
  const trimmed = path.trim();
  return trimmed.startsWith('/') && !trimmed.split('/').includes('..');
}

function inRange(value: number, min: number): boolean {
  return Number.isInteger(value) && value >= min && value <= KEEP_MAX;
}

function draftOf(plan: BackupPlan): Draft {
  return {
    kind: plan.kind,
    paths: plan.paths,
    folder: plan.paths[0] ?? '',
    pattern: plan.pattern,
    name: plan.name,
    schedule: scheduleOf(plan.interval_minutes),
    keep: plan.keep,
    keep_remote: plan.keep_remote,
    enabled: plan.enabled,
  };
}

function settingsOf(draft: Draft): PlanSettings | null {
  const collect = draft.kind === 'collect';
  const keepRemote = collect ? 0 : draft.keep_remote;
  if (draft.keep === null || keepRemote === null) {
    return null;
  }
  return {
    name: draft.name.trim(),
    interval_minutes: PLAN_SCHEDULES[draft.schedule],
    keep: draft.keep,
    keep_remote: keepRemote,
    enabled: draft.enabled,
    paths: pathsOf(draft),
    pattern: patternOf(draft),
  };
}

function readsElsewhere(before: Draft, after: Draft): boolean {
  return (
    JSON.stringify(pathsOf(before)) !== JSON.stringify(pathsOf(after)) || patternOf(before) !== patternOf(after)
  );
}

function patternOf(draft: Draft): string {
  return draft.kind === 'collect' ? draft.pattern.trim() : '';
}

function pathsOf(draft: Draft): readonly string[] {
  switch (draft.kind) {
    case 'archive':
      return draft.paths.map((path) => path.trim());
    case 'collect':
      return [draft.folder.trim()];
    case 'dbs':
      return [];
  }
}
