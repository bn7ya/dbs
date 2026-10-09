import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { ButtonDirective } from 'primeng/button';
import { Card } from 'primeng/card';
import { IconField } from 'primeng/iconfield';
import { InputIcon } from 'primeng/inputicon';
import { InputText } from 'primeng/inputtext';
import { Message } from 'primeng/message';
import { Paginator } from 'primeng/paginator';
import { Skeleton } from 'primeng/skeleton';
import { TableModule } from 'primeng/table';
import type { PaginatorState } from 'primeng/types/paginator';
import type { TablePassThrough } from 'primeng/types/table';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { AppDatePipe } from '@shared/app-date/app-date.pipe';
import { Dialogs } from '@shared/dialogs/dialogs';
import { EmptyState } from '@shared/empty-state/empty-state';
import { Field } from '@shared/field/field';
import { FieldControl } from '@shared/field/field-control';
import { Toaster } from '@shared/toaster/toaster';
import { CheckStatusTag } from '../../components/check-status-tag/check-status-tag';
import { ServerForm } from '../../components/server-form/server-form';
import type { ServerFormData } from '../../components/server-form/server-form.types';
import type { Server } from '../../data/servers.types';
import { SERVER_PAGE_SIZES, ServersStore } from '../../state/servers.store';

@Component({
  selector: 'app-servers-page',
  imports: [
    FormsModule,
    RouterLink,
    ButtonDirective,
    Card,
    IconField,
    InputIcon,
    InputText,
    Message,
    Paginator,
    Skeleton,
    TableModule,
    AppDatePipe,
    EmptyState,
    Field,
    FieldControl,
    CheckStatusTag,
    ErrorTextPipe,
    TranslatePipe,
  ],
  providers: [Dialogs],
  templateUrl: './servers.html',
  styleUrl: './servers.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ServersPage {
  private readonly store = inject(ServersStore);
  private readonly dialogs = inject(Dialogs);
  private readonly toaster = inject(Toaster);
  private readonly locale = inject(LocaleStore);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

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

  readonly first = computed(() => this.page() * this.pageSize());

  readonly tablePt = computed<TablePassThrough>(() => ({
    table: { 'aria-label': this.locale.translate('servers.list.label') },
  }));

  constructor() {
    this.store.openList();
    inject(DestroyRef).onDestroy(() => this.store.closeList());
  }

  onSearch(text: string): void {
    this.store.setSearch(text);
  }

  onPaged(event: PaginatorState): void {
    const rows = event.rows ?? this.pageSize();
    this.store.goToPage(Math.floor((event.first ?? 0) / rows), rows);
  }

  retry(): void {
    this.store.reloadList();
  }

  async add(): Promise<void> {
    const created = await this.dialogs
      .open<Server, ServerFormData>(ServerForm, {
        titleKey: 'servers.form.addTitle',
        data: { server: null },
        size: 'lg',
      })
      .whenClosed();
    if (created) {
      this.toaster.add({ severity: 'success', summary: this.locale.translate('servers.form.added') });
      await this.router.navigate([created.id], { relativeTo: this.route });
    }
  }
}
