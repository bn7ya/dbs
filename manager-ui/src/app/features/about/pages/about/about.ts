import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MatButton } from '@angular/material/button';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { AppDatePipe } from '@shared/app-date/app-date.pipe';
import { CopyButton } from '@shared/copy-button/copy-button';
import { Notice } from '@shared/notice/notice';
import { Skeleton } from '@shared/skeleton/skeleton';
import { TimeAgoPipe } from '@shared/time-ago/time-ago.pipe';
import { uniqueId } from '@shared/unique-id';
import { AboutStore } from '../../state/about.store';
import type { AboutCommand } from './about.types';

const COMMANDS: readonly AboutCommand[] = [
  { key: 'export', text: 'django_dbs export manager.dbs' },
  { key: 'exportWithBackups', text: 'django_dbs export manager.dbs --with-backups' },
  { key: 'import', text: 'django_dbs import manager.dbs' },
];

@Component({
  selector: 'app-about-page',
  imports: [MatButton, CopyButton, Notice, Skeleton, AppDatePipe, TimeAgoPipe, ErrorTextPipe, TranslatePipe],
  templateUrl: './about.html',
  styleUrl: './about.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AboutPage {
  private readonly store = inject(AboutStore);

  readonly about = this.store.about;
  readonly pending = this.store.pending;
  readonly error = this.store.error;

  readonly commands = COMMANDS;
  readonly skeletonLines = [1, 2, 3];
  readonly managerHeading = uniqueId('about-manager');
  readonly copyHeading = uniqueId('about-copy');

  retry(): void {
    this.store.reload();
  }
}
