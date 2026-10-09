import { ChangeDetectionStrategy, Component, DestroyRef, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { MatButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { MatFormField, MatLabel, MatPrefix } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';
import { MatPaginator, type PageEvent } from '@angular/material/paginator';
import { MatTableModule } from '@angular/material/table';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { AppDatePipe } from '@shared/app-date/app-date.pipe';
import { EmptyState } from '@shared/empty-state/empty-state';
import { Notice } from '@shared/notice/notice';
import { Skeleton } from '@shared/skeleton/skeleton';
import { CheckStatusTag } from '../../components/check-status-tag/check-status-tag';
import { SERVER_PAGE_SIZES, ServersStore } from '../../state/servers.store';

@Component({
  selector: 'app-servers-page',
  imports: [
    FormsModule,
    RouterLink,
    MatButton,
    MatCard,
    MatCardContent,
    MatFormField,
    MatLabel,
    MatPrefix,
    MatInput,
    MatPaginator,
    MatTableModule,
    Notice,
    Skeleton,
    AppDatePipe,
    EmptyState,
    CheckStatusTag,
    ErrorTextPipe,
    TranslatePipe,
  ],
  templateUrl: './servers.html',
  styleUrl: './servers.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ServersPage {
  private readonly store = inject(ServersStore);

  readonly search = this.store.search;
  readonly servers = this.store.servers;
  readonly count = this.store.count;
  readonly page = this.store.page;
  readonly pageSize = this.store.pageSize;
  readonly pageSizes = SERVER_PAGE_SIZES;
  readonly loading = this.store.listLoading;
  readonly pending = this.store.listPending;
  readonly error = this.store.listError;
  readonly empty = this.store.listEmpty;
  readonly searching = this.store.searching;
  readonly skeletonLines = [1, 2, 3, 4, 5, 6];

  readonly columns = ['name', 'address', 'status', 'lastChecked'];

  constructor() {
    this.store.openList();
    inject(DestroyRef).onDestroy(() => this.store.closeList());
  }

  onSearch(text: string): void {
    this.store.setSearch(text);
  }

  onPaged(event: PageEvent): void {
    this.store.goToPage(event.pageIndex, event.pageSize);
  }

  retry(): void {
    this.store.reloadList();
  }
}
