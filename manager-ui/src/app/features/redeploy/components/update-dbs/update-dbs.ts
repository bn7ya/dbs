import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MatCard, MatCardContent } from '@angular/material/card';

import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ConfirmedRun } from '@shared/confirmed-run/confirmed-run';
import type { RunRequest } from '@shared/confirmed-run/confirmed-run.types';
import { Notice } from '@shared/notice/notice';
import { uniqueId } from '@shared/unique-id';
import { DeployStore } from '../../state/deploy.store';
import { JobProgress } from '../job-progress/job-progress';
import { RevertPanel } from '../revert-panel/revert-panel';

@Component({
  selector: 'app-update-dbs',
  imports: [MatCard, MatCardContent, ConfirmedRun, JobProgress, Notice, RevertPanel, TranslatePipe],
  templateUrl: './update-dbs.html',
  styleUrl: './update-dbs.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class UpdateDbs {
  readonly headingId = uniqueId('update-dbs-title');

  private readonly store = inject(DeployStore);

  readonly application = this.store.application;
  readonly updating = this.store.updating;
  readonly undoing = this.store.undoingUpdate;
  readonly outcome = this.store.updateOutcome;

  update(request: RunRequest): void {
    this.store.updateDbs(request);
  }

  restore(request: RunRequest): void {
    this.store.revertUpdate(request);
  }

  clearRunError(): void {
    this.updating.clearError();
  }

  clearRevertError(): void {
    this.undoing.clearError();
  }
}
