import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { MatButton } from '@angular/material/button';
import { MatPaginator, type PageEvent } from '@angular/material/paginator';
import { MatTableModule } from '@angular/material/table';

import { Can } from '@core/auth/directives/can';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { AppDatePipe } from '@shared/app-date/app-date.pipe';
import { Dialogs } from '@shared/dialogs/dialogs';
import { Downloader } from '@shared/downloader/downloader';
import { FileSizePipe } from '@shared/file-size/file-size.pipe';
import { isolated } from '@shared/isolated/isolated';
import { PasswordPrompt } from '@shared/password-prompt/password-prompt';
import type { PasswordPromptData } from '@shared/password-prompt/password-prompt.types';
import { StatusTag } from '@shared/status-tag/status-tag';
import type { BackupFile, BackupValidation } from '../../data/backups.types';
import { BACKUP_PAGE_SIZES, BackupsStore } from '../../state/backups.store';
import type { RestoreProgress } from '../../state/backups.store.types';
import { RestoreForm } from '../restore-form/restore-form';
import type { RestoreFormData } from '../restore-form/restore-form.types';
import type { BackupColumn, TagLook } from './backup-table.types';

const VALIDATION_LOOKS: Readonly<Record<BackupValidation, TagLook>> = {
  structure_ok: { severity: 'neutral', icon: 'fa-solid fa-check' },
  verified: { severity: 'success', icon: 'fa-solid fa-shield-halved' },
  failed: { severity: 'danger', icon: 'fa-solid fa-circle-exclamation' },
};

const COLUMNS: readonly BackupColumn[] = ['name', 'taken', 'plan', 'size', 'check', 'actions'];

const OWNED_COLUMNS: readonly BackupColumn[] = [
  'name',
  'application',
  'server',
  'taken',
  'plan',
  'size',
  'check',
  'actions',
];

@Component({
  selector: 'app-backup-table',
  imports: [Can, RouterLink, MatButton, MatPaginator, MatTableModule, StatusTag, AppDatePipe, FileSizePipe, TranslatePipe],
  templateUrl: './backup-table.html',
  styleUrl: './backup-table.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BackupTable {
  private readonly store = inject(BackupsStore);
  private readonly dialogs = inject(Dialogs);
  private readonly locale = inject(LocaleStore);
  private readonly downloader = inject(Downloader);

  readonly owners = input(false);
  readonly label = input.required<string>();

  readonly rows = computed(() => [...this.store.files()]);
  readonly columns = computed(() => [...(this.owners() ? OWNED_COLUMNS : COLUMNS)]);
  readonly count = this.store.count;
  readonly page = this.store.page;
  readonly pageSize = this.store.pageSize;
  readonly pageSizes = [...BACKUP_PAGE_SIZES];
  readonly loading = this.store.loading;

  readonly paginated = computed(() => this.count() > BACKUP_PAGE_SIZES[0]);

  look(validation: BackupValidation): TagLook {
    return VALIDATION_LOOKS[validation];
  }

  validationKey(file: BackupFile): string {
    if (file.failure !== '') {
      return 'backups.validation.quarantined';
    }
    return `backups.${file.kind === 'dbs' ? 'validation' : 'sealedValidation'}.${file.validation}`;
  }

  takenBy(file: BackupFile): string | null {
    return file.taken_by === null ? null : this.locale.translate('backups.list.by', { name: isolated(file.taken_by) });
  }

  downloadUrl(file: BackupFile): string {
    return this.store.downloadUrl(file);
  }

  // Everything but a django-dbs backup is kept sealed here, and downloading it decrypts it.
  sealed(file: BackupFile): boolean {
    return file.kind !== 'dbs';
  }

  async download(file: BackupFile): Promise<void> {
    const data: PasswordPromptData = {
      titleKey: 'backups.download.prompt.title',
      bodyKey: 'backups.download.prompt.body',
      bodyValues: { name: isolated(file.name) },
      submitKey: 'backups.download.action',
      submit: async (password) => {
        const url = await this.store.downloadLink(file, password);
        if (url === null) {
          return false;
        }
        this.downloader.start(url);
        return true;
      },
      error: this.store.downloadError,
    };
    await this.dialogs
      .open<boolean, PasswordPromptData>(PasswordPrompt, { titleKey: data.titleKey, data, size: 'sm' })
      .whenClosed();
  }

  isVerifying(file: BackupFile): boolean {
    return this.store.isVerifying(file);
  }

  isDeleting(file: BackupFile): boolean {
    return this.store.deleting().has(file.id);
  }

  verify(file: BackupFile): void {
    this.store.verify(file);
  }

  restoring(file: BackupFile): RestoreProgress | null {
    return this.store.restoring(file);
  }

  restoreKey(file: BackupFile): string {
    switch (this.store.restoring(file)) {
      case 'rehearse':
        return 'backups.restore.rehearsing';
      case 'restore':
        return 'backups.restore.working';
      default:
        return 'backups.restore.action';
    }
  }

  canRestore(file: BackupFile): boolean {
    return file.kind === 'dbs' && file.failure === '';
  }

  restore(file: BackupFile): void {
    this.dialogs.open<boolean, RestoreFormData>(RestoreForm, {
      titleKey: 'backups.restore.title',
      data: { file },
      size: 'md',
    });
  }

  async remove(file: BackupFile): Promise<void> {
    const data: PasswordPromptData = {
      titleKey: 'backups.delete.prompt.title',
      bodyKey: 'backups.delete.prompt.body',
      bodyValues: { name: isolated(file.name) },
      submitKey: 'actions.delete',
      destructive: true,
      submit: (password) => this.store.remove(file, password),
      error: this.store.deleteError,
    };
    await this.dialogs
      .open<boolean, PasswordPromptData>(PasswordPrompt, { titleKey: data.titleKey, data, size: 'sm' })
      .whenClosed();
  }

  onPaged(event: PageEvent): void {
    this.store.goToPage(event.pageIndex, event.pageSize);
  }
}
