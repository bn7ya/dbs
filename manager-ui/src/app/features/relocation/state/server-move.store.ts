import { Injectable, computed, inject, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';

import { apiErrorOf } from '@core/http/api-error';
import { JobRun } from '@core/jobs/job-run';
import { isFinished } from '@core/jobs/job.types';
import type { RunRequest } from '@shared/confirmed-run/confirmed-run.types';
import { moveDetailOf } from '../data/move-detail';
import { RelocationApi } from '../data/relocation.api';
import type { MoveChoice, MoveDetail, MoveServer } from '../data/relocation.types';

@Injectable()
export class ServerMoveStore {
  private readonly api = inject(RelocationApi);

  private readonly sourceId = signal<string | null>(null);

  private readonly sourceResource = rxResource({
    params: () => this.sourceId() ?? undefined,
    stream: ({ params }) => this.api.server(params),
  });

  private readonly serversResource = rxResource({
    params: () => this.sourceId() ?? undefined,
    stream: () => this.api.servers().pipe(map((page) => page.results)),
  });

  private readonly applicationsResource = rxResource({
    params: () => this.sourceId() ?? undefined,
    stream: ({ params }) => this.api.applications(params).pipe(map((page) => page.results)),
  });

  readonly planning = new JobRun();
  readonly moving = new JobRun();

  readonly source = computed<MoveServer | undefined>(() =>
    this.sourceResource.hasValue() ? this.sourceResource.value() : undefined,
  );
  readonly targets = computed<readonly MoveServer[]>(() =>
    (this.serversResource.hasValue() ? this.serversResource.value() : []).filter((server) => server.id !== this.sourceId()),
  );
  readonly applications = computed(() => (this.applicationsResource.hasValue() ? this.applicationsResource.value() : []));
  readonly loading = computed(
    () => this.sourceResource.isLoading() || this.serversResource.isLoading() || this.applicationsResource.isLoading(),
  );
  readonly loadError = computed(
    () =>
      apiErrorOf(this.sourceResource.error()) ??
      apiErrorOf(this.serversResource.error()) ??
      apiErrorOf(this.applicationsResource.error()),
  );

  readonly plan = computed<MoveDetail | null>(() => {
    const job = this.planning.job();
    return job ? moveDetailOf(job.detail) : null;
  });
  readonly planned = computed(() => {
    const job = this.planning.job();
    return job !== null && job.status === 'succeeded';
  });
  readonly planBlocked = computed(() => this.planning.job()?.error_code === 'move_blocked');
  readonly progress = computed<MoveDetail | null>(() => {
    const job = this.moving.job();
    return job ? moveDetailOf(job.detail) : null;
  });
  readonly moveFinished = computed(() => {
    const job = this.moving.job();
    return job !== null && isFinished(job);
  });

  open(serverId: string | null): void {
    this.sourceId.set(serverId);
    this.planning.forget();
    this.moving.forget();
  }

  rehearse(target: string, applications: readonly MoveChoice[]): void {
    const source = this.sourceId();
    if (!source) {
      return;
    }
    this.planning.start(
      true,
      this.api.move(source, {
        target_server: target,
        applications,
        rehearsal: true,
        password: '',
        confirm_name: '',
        sudo_password: '',
        source_sudo_password: '',
      }),
    );
  }

  move(
    target: string,
    applications: readonly MoveChoice[],
    run: RunRequest,
    sudoPassword: string,
    sourceSudoPassword: string,
    resumeOf: number | null,
  ): void {
    const source = this.sourceId();
    if (!source) {
      return;
    }
    this.moving.start(
      false,
      this.api.move(source, {
        target_server: target,
        applications,
        rehearsal: false,
        password: run.password,
        confirm_name: run.confirm_name,
        sudo_password: sudoPassword,
        source_sudo_password: sourceSudoPassword,
        ...(resumeOf === null ? {} : { resume_of: resumeOf }),
      }),
    );
  }
}
