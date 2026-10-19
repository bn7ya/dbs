import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButton } from '@angular/material/button';

import type { ApiError } from '@core/http/api.types';
import { ErrorTextPipe, errorText } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { injectDialogData, injectDialogRef } from '@shared/dialogs/dialogs';
import { isolated } from '@shared/isolated/isolated';
import { Notice } from '@shared/notice/notice';
import type { BackupPlan } from '../../data/plans.types';
import { isoOf, momentProblem, partsOf, shownZone } from '../../data/zoned-time';
import type { MomentPart, MomentParts, MomentProblem } from '../../data/zoned-time.types';
import { PlansStore } from '../../state/plans.store';
import { MomentFields } from '../moment-fields/moment-fields';
import type { RescheduleFormData } from './reschedule-form.types';

@Component({
  selector: 'app-reschedule-form',
  imports: [FormsModule, MatButton, MomentFields, Notice, ErrorTextPipe, TranslatePipe],
  templateUrl: './reschedule-form.html',
  styleUrl: './reschedule-form.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RescheduleForm {
  private readonly store = inject(PlansStore);
  private readonly locale = inject(LocaleStore);
  private readonly ref = injectDialogRef<BackupPlan>();

  readonly plan = injectDialogData<RescheduleFormData>().plan;

  readonly zone = shownZone(this.plan.time_zone);

  readonly moment = signal<MomentParts>(partsOf(this.plan.next_run_at, this.zone));

  readonly saving = this.store.rescheduling;

  private readonly saveError = this.store.rescheduleError;

  private readonly attempted = signal(false);

  private readonly edited = signal(false);

  readonly body = computed(() => this.locale.translate('backups.plans.reschedule.body', { name: isolated(this.plan.name) }));

  readonly hint = computed(() => this.locale.translate('backups.plans.reschedule.hint', { zone: isolated(this.zone) }));

  private readonly problem = computed<MomentProblem | null>(() => {
    const parts = this.moment();
    if (parts.day === null && parts.time === null) {
      return { part: 'day', code: 'required' };
    }
    return momentProblem(parts, this.zone, Date.now());
  });

  private readonly refused = computed(() =>
    this.edited() ? null : (this.saveError()?.fields?.['next_run_at']?.[0] ?? null),
  );

  // The dialog has one field; any other refusal, such as `manual_plan`, is said in its own words.
  readonly formFailure = computed<ApiError | string | null>(() => {
    const failure = this.saveError();
    const fields = failure?.fields ?? {};
    if (failure === null || 'next_run_at' in fields) {
      return null;
    }
    return Object.values(fields)[0]?.[0] ?? failure;
  });

  constructor() {
    this.store.resetRescheduleForm();
  }

  errorFor(part: MomentPart): string {
    const problem = this.attempted() ? this.problem() : null;
    const code = problem?.part === part ? problem.code : part === 'day' ? this.refused() : null;
    return code === null ? '' : errorText(this.locale, code);
  }

  setDay(day: Date | null): void {
    this.moment.update((moment) => ({ ...moment, day }));
    this.edited.set(true);
  }

  setTime(time: Date | null): void {
    this.moment.update((moment) => ({ ...moment, time }));
    this.edited.set(true);
  }

  cancel(): void {
    this.ref.close();
  }

  async save(): Promise<void> {
    this.attempted.set(true);
    const nextRunAt = isoOf(this.moment(), this.zone);
    if (this.problem() !== null || nextRunAt === null) {
      return;
    }
    this.edited.set(false);
    const saved = await this.store.reschedule(this.plan, nextRunAt);
    if (saved) {
      this.ref.close(saved);
    }
  }
}
