import { ChangeDetectionStrategy, Component, DestroyRef, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { MatButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { MatFormField, MatLabel, MatPrefix } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';
import { MatPaginator, type PageEvent } from '@angular/material/paginator';
import { MatTableModule } from '@angular/material/table';

import { ErrorTextPipe, errorText } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { Can } from '@core/auth/directives/can';
import { AppDatePipe } from '@shared/app-date/app-date.pipe';
import { Confirmation } from '@shared/confirm/confirmation';
import { EmptyState } from '@shared/empty-state/empty-state';
import { Notice } from '@shared/notice/notice';
import { Skeleton } from '@shared/skeleton/skeleton';
import { Toaster } from '@shared/toaster/toaster';
import { CheckStatusTag } from '../../components/check-status-tag/check-status-tag';
import { HostKeyFacts } from '../../components/host-key-facts/host-key-facts';
import type { HostKeyConfirmation, HostKeyDecision } from '../../data/servers.types';
import { SERVER_PAGE_SIZES, ServersStore } from '../../state/servers.store';

@Component({
  selector: 'app-servers-page',
  imports: [
    Can,
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
    HostKeyFacts,
    ErrorTextPipe,
    TranslatePipe,
  ],
  templateUrl: './servers.html',
  styleUrl: './servers.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ServersPage {
  private readonly store = inject(ServersStore);
  private readonly confirmation = inject(Confirmation);
  private readonly toaster = inject(Toaster);
  private readonly locale = inject(LocaleStore);

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

  readonly pendingHostKeys = this.store.pendingHostKeys;

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

  addressOf(key: HostKeyConfirmation): string {
    return key.host.includes(':') ? `[${key.host}]:${key.port}` : `${key.host}:${key.port}`;
  }

  isDeciding(key: HostKeyConfirmation): boolean {
    return this.store.decidingHostKeys().has(key.id);
  }

  async confirmHostKey(key: HostKeyConfirmation): Promise<void> {
    const accepted = await this.confirmation.ask({
      // LRI and PDI keep the address left to right inside a title in either language.
      title: this.locale.translate('servers.pendingKeys.confirmTitle', { address: `\u2066${this.addressOf(key)}\u2069` }),
      message: this.locale.translate('servers.pendingKeys.confirmBody'),
      acceptLabel: this.locale.translate('servers.pendingKeys.confirm'),
      rejectLabel: this.locale.translate('actions.cancel'),
    });
    if (accepted) {
      await this.decide(key, 'confirm', 'servers.pendingKeys.confirmed');
    }
  }

  async rejectHostKey(key: HostKeyConfirmation): Promise<void> {
    await this.decide(key, 'reject', 'servers.pendingKeys.rejected');
  }

  private async decide(key: HostKeyConfirmation, decision: HostKeyDecision, doneKey: string): Promise<void> {
    if (await this.store.decideHostKey(key, decision)) {
      this.toaster.add({ severity: 'success', summary: this.locale.translate(doneKey) });
    } else {
      this.toaster.add({ severity: 'danger', summary: errorText(this.locale, this.store.hostKeyDecisionError()) });
    }
  }
}
