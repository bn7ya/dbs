import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { MatButton } from '@angular/material/button';
import { MatPaginator, type PageEvent } from '@angular/material/paginator';
import { MatTableModule } from '@angular/material/table';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { AppDatePipe } from '@shared/app-date/app-date.pipe';
import { injectDialogData, injectDialogRef } from '@shared/dialogs/dialogs';
import { EmptyState } from '@shared/empty-state/empty-state';
import { FileSizePipe } from '@shared/file-size/file-size.pipe';
import { Notice } from '@shared/notice/notice';
import { Skeleton } from '@shared/skeleton/skeleton';
import type { RemoteEntry, RemoteEntryKind } from '../../data/servers.types';
import { BROWSER_PAGE_SIZES, ServerBrowserStore } from '../../state/server-browser.store';
import type { ServerBrowserData } from './server-browser.types';

const KIND_ICONS: Readonly<Record<RemoteEntryKind, string>> = {
  folder: 'fa-solid fa-folder',
  file: 'fa-regular fa-file',
  link: 'fa-solid fa-link',
  other: 'fa-solid fa-file-circle-question',
};

const SKELETON_LINES: readonly number[] = [1, 2, 3, 4, 5];

@Component({
  selector: 'app-server-browser',
  imports: [
    MatButton,
    MatPaginator,
    MatTableModule,
    EmptyState,
    Notice,
    Skeleton,
    AppDatePipe,
    ErrorTextPipe,
    FileSizePipe,
    TranslatePipe,
  ],
  providers: [ServerBrowserStore],
  templateUrl: './server-browser.html',
  styleUrl: './server-browser.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ServerBrowser {
  private readonly store = inject(ServerBrowserStore);
  private readonly ref = injectDialogRef<string>();
  protected readonly data = injectDialogData<ServerBrowserData>();

  readonly pageSizes = BROWSER_PAGE_SIZES;
  readonly skeletonLines = SKELETON_LINES;
  readonly columns = ['name', 'size', 'modified'];

  readonly path = this.store.path;
  readonly entries = this.store.entries;
  readonly count = this.store.count;
  readonly page = this.store.page;
  readonly pageSize = this.store.pageSize;
  readonly isProject = this.store.isProject;
  readonly truncated = this.store.truncated;
  readonly loading = this.store.loading;
  readonly pending = this.store.pending;
  readonly error = this.store.error;
  readonly empty = this.store.empty;
  readonly trail = this.store.trail;

  readonly picksFolders = this.data.mode === 'folder';
  readonly projects = this.data.projects;
  readonly paginated = computed(() => this.count() > BROWSER_PAGE_SIZES[0]);
  readonly atTop = computed(() => this.path() === '/');

  constructor() {
    this.store.open(this.data.serverId, this.data.start || null);
  }

  iconOf(entry: RemoteEntry): string {
    return KIND_ICONS[entry.kind];
  }

  opens(entry: RemoteEntry): boolean {
    return entry.kind === 'folder' || entry.kind === 'link';
  }

  picks(entry: RemoteEntry): boolean {
    return !this.picksFolders && entry.kind === 'file';
  }

  go(path: string): void {
    this.store.go(path);
  }

  up(): void {
    this.store.up();
  }

  home(): void {
    this.store.home();
  }

  onPaged(event: PageEvent): void {
    this.store.goToPage(event.pageIndex, event.pageSize);
  }

  retry(): void {
    this.store.reload();
  }

  choose(path: string): void {
    this.ref.close(path);
  }

  chooseHere(): void {
    const path = this.path();
    if (path !== null) {
      this.ref.close(path);
    }
  }

  cancel(): void {
    this.ref.close();
  }
}
