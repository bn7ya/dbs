import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  afterRenderEffect,
  computed,
  effect,
  inject,
  signal,
  viewChild,
  type Signal,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { MatButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { MatOption } from '@angular/material/core';
import { MatFormField, MatLabel } from '@angular/material/form-field';
import { MatPaginator, type PageEvent } from '@angular/material/paginator';
import { MatProgressBar } from '@angular/material/progress-bar';
import { MatSelect } from '@angular/material/select';
import { MatTableModule } from '@angular/material/table';
import { map } from 'rxjs';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { AppDatePipe } from '@shared/app-date/app-date.pipe';
import { Breadcrumb } from '@shared/breadcrumb/breadcrumb';
import type { BreadcrumbItem } from '@shared/breadcrumb/breadcrumb.types';
import { Confirmation } from '@shared/confirm/confirmation';
import { Dialogs } from '@shared/dialogs/dialogs';
import { EmptyState } from '@shared/empty-state/empty-state';
import { FileSizePipe } from '@shared/file-size/file-size.pipe';
import { Notice } from '@shared/notice/notice';
import { Skeleton } from '@shared/skeleton/skeleton';
import { StatusTag } from '@shared/status-tag/status-tag';
import { uniqueId } from '@shared/unique-id';
import { NewFolderDialog } from '../../components/new-folder/new-folder';
import type { NewFolderData } from '../../components/new-folder/new-folder.types';
import type { Entry, EntryKind } from '../../data/files.types';
import { FILE_PAGE_SIZES, FilesStore } from '../../state/files.store';

const KIND_ICONS: Readonly<Record<EntryKind, string>> = {
  folder: 'fa-solid fa-folder',
  file: 'fa-regular fa-file',
  link: 'fa-solid fa-link',
  other: 'fa-regular fa-file-circle-question',
};

const SKELETON_LINES: readonly number[] = [0, 1, 2, 3, 4, 5];

@Component({
  selector: 'app-files-page',
  imports: [
    FormsModule,
    RouterLink,
    MatButton,
    MatCard,
    MatCardContent,
    MatFormField,
    MatLabel,
    MatSelect,
    MatOption,
    MatPaginator,
    MatProgressBar,
    MatTableModule,
    Breadcrumb,
    Notice,
    Skeleton,
    StatusTag,
    EmptyState,
    AppDatePipe,
    ErrorTextPipe,
    FileSizePipe,
    TranslatePipe,
  ],
  providers: [Dialogs],
  templateUrl: './files.html',
  styleUrl: './files.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FilesPage {
  private readonly store = inject(FilesStore);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly dialogs = inject(Dialogs);
  private readonly confirmation = inject(Confirmation);
  private readonly locale = inject(LocaleStore);

  readonly serverId = serverIdOf(this.route);

  readonly path = toSignal(this.route.queryParamMap.pipe(map((params) => params.get('path'))), {
    requireSync: true,
  });

  readonly entries = this.store.entries;
  readonly count = this.store.count;
  readonly page = this.store.page;
  readonly pageSize = this.store.pageSize;
  readonly pageSizes = [...FILE_PAGE_SIZES];
  readonly skeletonLines = SKELETON_LINES;
  readonly loading = this.store.loading;
  readonly pending = this.store.pending;
  readonly error = this.store.error;
  readonly empty = this.store.empty;
  readonly noFolders = this.store.noFolders;
  readonly current = this.store.current;
  readonly roots = this.store.roots;
  readonly root = this.store.root;
  readonly upload = this.store.upload;
  readonly uploading = this.store.uploading;
  readonly uploadProgress = this.store.uploadProgress;

  readonly uploadLabelId = uniqueId('files-upload');

  readonly rows = computed(() => [...this.entries()]);

  readonly pickRoot = computed(() => this.roots().length > 1);

  readonly rootOptions = computed(() => [...this.roots()]);

  readonly crumbs = computed<BreadcrumbItem[]>(() =>
    this.store.trail().map((crumb) => ({
      label: crumb.name,
      link: [],
      queryParams: { path: crumb.path },
      icon: crumb.path === this.root() ? 'fa-solid fa-folder' : undefined,
    })),
  );

  readonly overviewLink = computed(() => ['/servers', this.serverId() ?? '']);

  readonly paginated = computed(() => this.count() > FILE_PAGE_SIZES[0]);

  private readonly uploadButton = viewChild<unknown, ElementRef<HTMLButtonElement>>('uploadButton', { read: ElementRef });

  private readonly location = viewChild<unknown, ElementRef<HTMLElement>>('location', { read: ElementRef });

  // The folder the last render showed, to tell when another one has arrived; bookkeeping, not state on screen.
  private lastShown: string | null = null;

  constructor() {
    effect(() => {
      const server = this.serverId();
      if (server !== null) {
        this.store.show(server, this.path());
      }
    });
    inject(DestroyRef).onDestroy(() => this.store.close());

    // Opening a folder from its row replaces the rows, link and all, and focus falls to the document.
    afterRenderEffect(() => {
      const shown = this.current();
      const previous = this.lastShown;
      if (shown === null || shown === previous) {
        return;
      }
      this.lastShown = shown;
      const focused = document.activeElement;
      if (previous !== null && (focused === null || focused === document.body)) {
        this.location()?.nativeElement.focus();
      }
    });
  }

  iconOf(entry: Entry): string {
    return KIND_ICONS[entry.kind];
  }

  downloadUrl(entry: Entry): string {
    return this.store.downloadUrl(entry);
  }

  isDeleting(entry: Entry): boolean {
    return this.store.isDeleting(entry);
  }

  onRoot(value: string | null): void {
    if (typeof value === 'string' && value !== this.root()) {
      void this.router.navigate([], { relativeTo: this.route, queryParams: { path: value } });
    }
  }

  onFileChosen(picker: HTMLInputElement): void {
    const file = picker.files?.item(0) ?? null;
    const folder = this.current();
    picker.value = '';
    if (file !== null && folder !== null) {
      this.store.uploadFile(folder, file);
    }
  }

  cancelUpload(): void {
    this.store.cancelUpload();
    this.uploadButton()?.nativeElement.focus();
  }

  newFolder(): void {
    const folder = this.current();
    if (folder === null) {
      return;
    }
    this.store.resetNewFolder();
    this.dialogs.open<Entry, NewFolderData>(NewFolderDialog, {
      titleKey: 'files.newFolder.title',
      data: { folder },
      size: 'sm',
    });
  }

  async remove(entry: Entry): Promise<void> {
    const folder = entry.kind === 'folder';
    const accepted = await this.confirmation.ask({
      title: this.locale.translate(folder ? 'files.delete.folderTitle' : 'files.delete.fileTitle'),
      message: leftToRight(entry.path),
      detail: this.locale.translate(folder ? 'files.delete.folderBody' : 'files.delete.fileBody'),
      acceptLabel: this.locale.translate('actions.delete'),
      rejectLabel: this.locale.translate('actions.cancel'),
      acceptSeverity: 'danger',
    });
    if (accepted) {
      await this.store.remove(entry);
    }
  }

  onPaged(event: PageEvent): void {
    this.store.goToPage(event.pageIndex, event.pageSize);
  }

  retry(): void {
    this.store.reload();
  }
}

// LRI ... PDI: the confirmation draws its message as plain text, with no dir of its own to set.
function leftToRight(text: string): string {
  return `⁦${text}⁩`;
}

// Param inheritance stops at the server page, a route with its own component, so the param is read
// from the route that declares it, as the backups and activity tabs do.
function serverIdOf(route: ActivatedRoute): Signal<string | null> {
  const owner = route.pathFromRoot.find((step) => step.snapshot.paramMap.has('serverId'));
  if (!owner) {
    return signal(null).asReadonly();
  }
  return toSignal(owner.paramMap.pipe(map((params) => params.get('serverId'))), { requireSync: true });
}
