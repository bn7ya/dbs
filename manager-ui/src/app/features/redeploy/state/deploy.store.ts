import { Injectable, computed, inject, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { firstValueFrom } from 'rxjs';

import { apiErrorOf } from '@core/http/api-error';
import type { ApiError } from '@core/http/api.types';
import { LocaleStore } from '@core/i18n/locale.store';
import { Toaster } from '@shared/toaster/toaster';
import { deployOutcomeOf } from '../data/job-detail';
import { RedeployApi } from '../data/redeploy.api';
import type { DeployStep, RunRequest } from '../data/redeploy.types';
import { JobRun } from './job-run';

const STEP_FIELD = /^steps\.(\d+)$/;
const STEPS_FIELD = 'steps';

@Injectable()
export class DeployStore {
  private readonly api = inject(RedeployApi);
  private readonly toast = inject(Toaster);
  private readonly locale = inject(LocaleStore);

  private readonly applicationId = signal<string | null>(null);

  private readonly applicationResource = rxResource({
    params: () => this.applicationId() ?? undefined,
    stream: ({ params }) => this.api.application(params),
  });

  readonly application = computed(() => (this.applicationResource.hasValue() ? this.applicationResource.value() : null));
  readonly loadError = computed(() => apiErrorOf(this.applicationResource.error()));

  open(application: string): void {
    this.applicationId.set(application);
  }

  reload(): void {
    this.applicationResource.reload();
  }

  readonly saving = signal(false);
  readonly saveError = signal<ApiError | null>(null);

  readonly stepErrors = computed<ReadonlyMap<number, readonly string[]>>(() => {
    const found = new Map<number, readonly string[]>();
    for (const [field, codes] of Object.entries(this.saveError()?.fields ?? {})) {
      const index = STEP_FIELD.exec(field)?.[1];
      if (index !== undefined) {
        found.set(Number(index), codes);
      }
    }
    return found;
  });

  readonly listErrors = computed<readonly string[]>(() => this.saveError()?.fields?.[STEPS_FIELD] ?? []);

  // Refused for the steps themselves: the rows say why, so the password prompt has nothing to retry.
  readonly stepsRefused = computed(() => this.stepErrors().size > 0 || this.listErrors().length > 0);

  clearSaveError(): void {
    this.saveError.set(null);
  }

  async saveSteps(steps: readonly DeployStep[], password: string): Promise<boolean> {
    const application = this.applicationId();
    if (application === null || this.saving()) {
      return false;
    }
    this.saving.set(true);
    this.saveError.set(null);
    try {
      const saved = await firstValueFrom(this.api.saveSteps(application, { steps, account_password: password }));
      if (this.applicationId() === application) {
        this.applicationResource.set(saved);
      }
    } catch (error) {
      this.saveError.set(error as ApiError);
      return false;
    } finally {
      this.saving.set(false);
    }
    this.toast.add({ severity: 'success', summary: this.locale.translate('redeploy.editor.saved') });
    return true;
  }

  readonly deploying = new JobRun();
  readonly reverting = new JobRun();

  readonly outcome = computed(() => deployOutcomeOf(this.deploying.job()?.detail ?? {}));

  deploy(request: RunRequest): void {
    const application = this.applicationId();
    if (application === null || this.deploying.busy()) {
      return;
    }
    this.reverting.forget();
    this.deploying.start(request.rehearsal, this.api.deploy(application, request));
  }

  revert(request: RunRequest): void {
    const job = this.deploying.job();
    if (job === null) {
      return;
    }
    this.reverting.start(request.rehearsal, this.api.revert(job.id, request));
  }
}
