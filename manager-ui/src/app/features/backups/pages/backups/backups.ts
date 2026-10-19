import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  Injector,
  afterNextRender,
  effect,
  inject,
  viewChild,
} from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { MatButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { MatProgressBar } from '@angular/material/progress-bar';

import { Can } from '@core/auth/directives/can';
import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { routeParam } from '@core/routing/route-param';
import { Dialogs } from '@shared/dialogs/dialogs';
import { EmptyState } from '@shared/empty-state/empty-state';
import { Notice } from '@shared/notice/notice';
import { Skeleton } from '@shared/skeleton/skeleton';
import { uniqueId } from '@shared/unique-id';
import { BackupNotices } from '../../components/backup-notices/backup-notices';
import { BackupTable } from '../../components/backup-table/backup-table';
import { BackupsStore } from '../../state/backups.store';

@Component({
  selector: 'app-backups-page',
  imports: [
    BackupNotices,
    BackupTable,
    Can,
    MatButton,
    MatCard,
    MatCardContent,
    MatProgressBar,
    Notice,
    Skeleton,
    EmptyState,
    ErrorTextPipe,
    TranslatePipe,
  ],
  providers: [Dialogs],
  templateUrl: './backups.html',
  styleUrl: './backups.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BackupsPage {
  private readonly store = inject(BackupsStore);
  private readonly injector = inject(Injector);

  readonly applicationId = routeParam(inject(ActivatedRoute), 'applicationId');

  readonly pending = this.store.pending;
  readonly error = this.store.error;
  readonly empty = this.store.empty;
  readonly taking = this.store.taking;
  readonly upload = this.store.upload;
  readonly uploading = this.store.uploading;
  readonly uploadProgress = this.store.uploadProgress;

  readonly uploadLabelId = uniqueId('backups-upload');
  readonly skeleton = [0, 1, 2, 3, 4, 5];

  private readonly uploadButton = viewChild.required<unknown, ElementRef<HTMLButtonElement>>('uploadButton', {
    read: ElementRef,
  });

  constructor() {
    effect(() => {
      const application = this.applicationId();
      if (application !== null) {
        this.store.openApplication(application);
      }
    });
    inject(DestroyRef).onDestroy(() => this.store.close());
  }

  take(): void {
    this.store.take();
  }

  // Emptied first, so choosing the same file again is still a change.
  onFileChosen(picker: HTMLInputElement): void {
    const file = picker.files?.item(0) ?? null;
    picker.value = '';
    if (file !== null) {
      this.store.uploadFile(file);
    }
  }

  // Cancel leaves with the upload; focus goes back once the button that started it is enabled again.
  cancelUpload(): void {
    this.store.cancelUpload();
    afterNextRender(() => this.uploadButton().nativeElement.focus(), {
      injector: this.injector,
    });
  }

  retry(): void {
    this.store.reload();
  }
}
