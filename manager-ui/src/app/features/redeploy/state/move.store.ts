import { Injectable, computed, inject, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';

import { apiErrorOf } from '@core/http/api-error';
import { moveOutcomeOf } from '../data/job-detail';
import { RedeployApi } from '../data/redeploy.api';
import type { RunRequest } from '@shared/confirmed-run/confirmed-run.types';
import type { MoveRequest } from '../data/redeploy.types';
import { JobRun } from '@core/jobs/job-run';

const DJANGO_DBS_BACKUP = 'dbs';

@Injectable()
export class MoveStore {
  private readonly api = inject(RedeployApi);

  readonly source = signal<string | null>(null);

  private readonly applicationsResource = rxResource({
    params: () => this.source() ?? undefined,
    stream: () => this.api.applications(),
  });
  private readonly backupsResource = rxResource({
    params: () => this.source() ?? undefined,
    stream: ({ params }) => this.api.backups(params),
  });
  private readonly envResource = rxResource({
    params: () => this.source() ?? undefined,
    stream: ({ params }) => this.api.envVersions(params),
  });

  private readonly applications = computed(() =>
    this.applicationsResource.hasValue() ? this.applicationsResource.value().results : [],
  );

  readonly targets = computed(() => {
    const source = this.source();
    return this.applications().filter((application) => application.id !== source);
  });

  readonly backups = computed(() =>
    (this.backupsResource.hasValue() ? this.backupsResource.value().results : []).filter(
      (backup) => backup.kind === DJANGO_DBS_BACKUP,
    ),
  );
  readonly envVersions = computed(() => (this.envResource.hasValue() ? this.envResource.value().results : []));

  readonly loading = computed(
    () => this.applicationsResource.isLoading() || this.backupsResource.isLoading() || this.envResource.isLoading(),
  );
  readonly loadError = computed(
    () =>
      apiErrorOf(this.applicationsResource.error()) ??
      apiErrorOf(this.backupsResource.error()) ??
      apiErrorOf(this.envResource.error()),
  );

  readonly moving = new JobRun();
  readonly reverting = new JobRun();

  readonly outcome = computed(() => moveOutcomeOf(this.moving.job()?.detail ?? {}));

  readonly movedTo = computed(() => {
    const target = this.outcome().target;
    return this.applications().find((application) => application.id === target) ?? null;
  });

  open(source: string): void {
    this.source.set(source);
  }

  reload(): void {
    this.applicationsResource.reload();
    this.backupsResource.reload();
    this.envResource.reload();
  }

  move(request: MoveRequest): void {
    if (this.moving.busy()) {
      return;
    }
    this.reverting.forget();
    this.moving.start(request.rehearsal, this.api.move(request));
  }

  revert(request: RunRequest): void {
    const job = this.moving.job();
    if (job === null) {
      return;
    }
    this.reverting.start(request.rehearsal, this.api.revert(job.id, request));
  }
}
