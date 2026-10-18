import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, linkedSignal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { MatButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { MatOption } from '@angular/material/core';
import { MatFormField, MatLabel } from '@angular/material/form-field';
import { MatPaginator, type PageEvent } from '@angular/material/paginator';
import { MatSelect } from '@angular/material/select';
import { MatTableModule } from '@angular/material/table';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { Dialogs } from '@shared/dialogs/dialogs';
import { EmptyState } from '@shared/empty-state/empty-state';
import { FileSizePipe } from '@shared/file-size/file-size.pipe';
import { isolated } from '@shared/isolated/isolated';
import { Notice } from '@shared/notice/notice';
import { Skeleton } from '@shared/skeleton/skeleton';
import { BackupNotices } from '../../components/backup-notices/backup-notices';
import { BackupTable } from '../../components/backup-table/backup-table';
import type { ApplicationChoice } from '../../data/backups.types';
import { BackupsStore } from '../../state/backups.store';

const STORAGE_PAGE_SIZE = 10;

@Component({
  selector: 'app-all-backups-page',
  imports: [
    BackupNotices,
    BackupTable,
    FormsModule,
    RouterLink,
    MatButton,
    MatCard,
    MatCardContent,
    MatFormField,
    MatLabel,
    MatOption,
    MatPaginator,
    MatSelect,
    MatTableModule,
    EmptyState,
    Notice,
    Skeleton,
    ErrorTextPipe,
    FileSizePipe,
    TranslatePipe,
  ],
  providers: [Dialogs],
  templateUrl: './all-backups.html',
  styleUrl: './all-backups.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AllBackupsPage {
  private readonly store = inject(BackupsStore);
  private readonly locale = inject(LocaleStore);

  readonly filter = this.store.application;
  readonly applications = this.store.applications;
  readonly pending = this.store.pending;
  readonly error = this.store.error;
  readonly empty = this.store.empty;

  readonly storage = this.store.storage;
  readonly storageError = this.store.storageError;

  readonly storageColumns = ['application', 'server', 'size'];
  readonly storagePageSize = STORAGE_PAGE_SIZE;
  readonly skeleton = [0, 1, 2, 3, 4, 5];
  readonly storageSkeleton = [0, 1, 2];

  readonly stored = computed(() => this.storage()?.applications ?? []);

  readonly storagePage = linkedSignal({ source: () => this.stored().length, computation: () => 0 });

  readonly storageRows = computed(() => {
    const start = this.storagePage() * STORAGE_PAGE_SIZE;
    return this.stored().slice(start, start + STORAGE_PAGE_SIZE);
  });

  readonly storagePaginated = computed(() => this.stored().length > STORAGE_PAGE_SIZE);

  constructor() {
    this.store.openEvery();
    inject(DestroyRef).onDestroy(() => this.store.close());
  }

  applicationLabel(application: ApplicationChoice): string {
    return this.locale.translate('backups.applicationOnServer', {
      name: isolated(application.name),
      server: isolated(application.server.name),
    });
  }

  filterBy(application: string | null): void {
    this.store.filterBy(application);
  }

  showEvery(): void {
    this.store.filterBy(null);
  }

  onStoragePaged(event: PageEvent): void {
    this.storagePage.set(event.pageIndex);
  }

  retry(): void {
    this.store.reload();
  }

  retryStorage(): void {
    this.store.reloadStorage();
  }
}
