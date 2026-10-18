import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { MatButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { MatFormField, MatLabel, MatPrefix } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';
import { MatPaginator, type PageEvent } from '@angular/material/paginator';
import { MatTableModule } from '@angular/material/table';

import { Can } from '@core/auth/directives/can';
import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { routeParam } from '@core/routing/route-param';
import { AppDatePipe } from '@shared/app-date/app-date.pipe';
import { EmptyState } from '@shared/empty-state/empty-state';
import { Notice } from '@shared/notice/notice';
import { Skeleton } from '@shared/skeleton/skeleton';
import { CheckTag } from '../../components/check-tag/check-tag';
import { WhereItRuns } from '../../components/where-it-runs/where-it-runs';
import { APPLICATION_PAGE_SIZES, ApplicationsStore } from '../../state/applications.store';

@Component({
  selector: 'app-applications-page',
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
    AppDatePipe,
    EmptyState,
    Notice,
    Skeleton,
    CheckTag,
    WhereItRuns,
    ErrorTextPipe,
    TranslatePipe,
  ],
  templateUrl: './applications.html',
  styleUrl: './applications.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ApplicationsPage {
  private readonly store = inject(ApplicationsStore);

  readonly serverId = routeParam(inject(ActivatedRoute), 'serverId');
  readonly scoped = computed(() => this.serverId() !== null);
  readonly addLink = computed(() => ['/servers', this.serverId() ?? '', 'applications', 'new']);

  readonly search = this.store.search;
  readonly applications = this.store.applications;
  readonly count = this.store.count;
  readonly page = this.store.page;
  readonly pageSize = this.store.pageSize;
  readonly pageSizes = APPLICATION_PAGE_SIZES;
  readonly loading = this.store.listLoading;
  readonly pending = this.store.listPending;
  readonly error = this.store.listError;
  readonly empty = this.store.listEmpty;
  readonly searching = this.store.searching;
  readonly skeletonLines = [1, 2, 3, 4, 5];

  readonly columns = computed(() =>
    this.scoped() ? ['name', 'where', 'status', 'lastChecked'] : ['name', 'server', 'where', 'status', 'lastChecked'],
  );

  constructor() {
    effect(() => this.store.openList(this.serverId()));
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
