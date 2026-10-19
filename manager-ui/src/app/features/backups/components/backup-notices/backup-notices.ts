import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MatButton } from '@angular/material/button';

import { TranslatePipe } from '@core/i18n/translate.pipe';
import { JobConnection } from '@shared/job-connection/job-connection';
import { Notice } from '@shared/notice/notice';
import { BackupsStore } from '../../state/backups.store';

@Component({
  selector: 'app-backup-notices',
  imports: [MatButton, JobConnection, Notice, TranslatePipe],
  templateUrl: './backup-notices.html',
  styleUrl: './backup-notices.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BackupNotices {
  private readonly store = inject(BackupsStore);

  readonly backingUp = this.store.backingUp;
  readonly liveConnection = this.store.liveConnection;
  readonly deleted = this.store.deleted;
  readonly undoing = this.store.undoing;

  undoDelete(): void {
    void this.store.undoDelete();
  }

  dismissDeleted(): void {
    this.store.dismissDeleted();
  }
}
