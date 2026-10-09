import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MatButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { MatTableModule } from '@angular/material/table';
import { RouterLink } from '@angular/router';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { AppDatePipe } from '@shared/app-date/app-date.pipe';
import { EmptyState } from '@shared/empty-state/empty-state';
import { FileSizePipe } from '@shared/file-size/file-size.pipe';
import { Notice } from '@shared/notice/notice';
import { Skeleton } from '@shared/skeleton/skeleton';
import { StatusTag } from '@shared/status-tag/status-tag';
import { TimeAgoPipe } from '@shared/time-ago/time-ago.pipe';
import type { DashboardCheckStatus, DashboardServer, HealthStatus } from '../../data/dashboard.types';
import { DashboardStore } from '../../state/dashboard.store';
import type { TagLook } from './dashboard.types';

const CHECK_LOOKS: Readonly<Record<DashboardCheckStatus, TagLook>> = {
  unknown: { severity: 'neutral', icon: 'fa-solid fa-circle-question' },
  ok: { severity: 'success', icon: 'fa-solid fa-circle-check' },
  problem: { severity: 'warning', icon: 'fa-solid fa-triangle-exclamation' },
  failed: { severity: 'danger', icon: 'fa-solid fa-circle-xmark' },
};

const HEALTH_LOOKS: Readonly<Record<HealthStatus | 'unknown', TagLook>> = {
  ok: { severity: 'success', icon: 'fa-solid fa-heart-pulse' },
  warn: { severity: 'warning', icon: 'fa-solid fa-triangle-exclamation' },
  error: { severity: 'danger', icon: 'fa-solid fa-circle-xmark' },
  unknown: { severity: 'neutral', icon: 'fa-solid fa-circle-question' },
};

const EXPORT_COMMAND = 'django_dbs export manager.dbs';

@Component({
  selector: 'app-dashboard-page',
  imports: [
    RouterLink,
    MatButton,
    MatCard,
    MatCardContent,
    MatTableModule,
    EmptyState,
    Notice,
    Skeleton,
    StatusTag,
    AppDatePipe,
    FileSizePipe,
    TimeAgoPipe,
    ErrorTextPipe,
    TranslatePipe,
  ],
  templateUrl: './dashboard.html',
  styleUrl: './dashboard.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardPage {
  private readonly store = inject(DashboardStore);

  readonly servers = this.store.servers;
  readonly failures = this.store.failures;
  readonly pending = this.store.pending;
  readonly error = this.store.error;
  readonly empty = this.store.empty;
  readonly storageBytes = this.store.storageBytes;
  readonly failuresThisWeek = this.store.failuresThisWeek;
  readonly lastExportAt = this.store.lastExportAt;
  readonly exportDue = this.store.exportDue;

  readonly exportCommand = EXPORT_COMMAND;
  readonly skeletonLines = [1, 2, 3, 4];
  readonly failureColumns = ['when', 'server', 'target', 'reason'];

  checkLook(server: DashboardServer): TagLook {
    return CHECK_LOOKS[server.check_status];
  }

  healthStatus(server: DashboardServer): HealthStatus | 'unknown' {
    return server.health?.status ?? 'unknown';
  }

  healthLook(server: DashboardServer): TagLook {
    return HEALTH_LOOKS[this.healthStatus(server)];
  }

  retry(): void {
    this.store.reload();
  }
}
