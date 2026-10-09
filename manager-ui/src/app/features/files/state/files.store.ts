import { DestroyRef, Injectable, computed, inject, linkedSignal, signal } from '@angular/core';
import { rxResource, takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { finalize, firstValueFrom, type Subscription } from 'rxjs';

import { apiErrorOf } from '@core/http/api-error';
import type { ApiError } from '@core/http/api.types';
import { errorText } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { Toaster } from '@shared/toaster/toaster';
import { FilesApi } from '../data/files.api';
import { rootOf, trailOf } from '../data/files.types';
import type { Crumb, Entry, Listing, ListingQuery, UploadEvent } from '../data/files.types';
import type { KnownRootsSource, ShownSource, Upload } from './files.store.types';

export const FILE_PAGE_SIZES: readonly number[] = [50, 100, 200];

@Injectable()
export class FilesStore {
  private readonly api = inject(FilesApi);
  private readonly toast = inject(Toaster);
  private readonly locale = inject(LocaleStore);
  private readonly destroyRef = inject(DestroyRef);

  private readonly isOpen = signal(false);

  readonly server = signal<string | null>(null);

  readonly requested = signal<string | null>(null);

  show(server: string, path: string | null): void {
    this.server.set(server);
    this.requested.set(path);
    this.page.set(0);
    this.isOpen.set(true);
  }

  close(): void {
    this.isOpen.set(false);
  }

  readonly page = linkedSignal({
    source: () => `${this.server()}\n${this.requested()}`,
    computation: () => 0,
  });
  readonly pageSize = signal(FILE_PAGE_SIZES[0]);

  private readonly query = computed<ListingQuery | undefined>(() => {
    const server = this.isOpen() ? this.server() : null;
    return server === null
      ? undefined
      : { server, path: this.requested(), page: this.page() + 1, page_size: this.pageSize() };
  });

  private readonly listResource = rxResource({
    params: () => this.query(),
    stream: ({ params }) => this.api.list(params),
  });

  private readonly shown = linkedSignal<ShownSource, Listing | undefined>({
    source: () => {
      const query = this.query();
      return {
        place: query === undefined ? null : `${query.server}\n${query.path}`,
        listing: this.listResource.hasValue() ? this.listResource.value() : undefined,
      };
    },
    computation: ({ place, listing }, previous) =>
      listing ?? (place !== null && place === previous?.source.place ? previous.value : undefined),
  });

  readonly entries = computed<readonly Entry[]>(() => this.shown()?.results ?? []);
  readonly count = computed(() => this.shown()?.count ?? 0);
  readonly loading = this.listResource.isLoading;
  readonly error = computed(() => apiErrorOf(this.listResource.error()));

  readonly pending = computed(() => this.shown() === undefined && this.loading());

  readonly empty = computed(() => this.shown()?.count === 0);

  readonly noFolders = computed(() => this.error()?.code === 'no_allowed_folders');

  readonly current = computed(() => this.shown()?.path ?? null);

  private readonly knownRoots = linkedSignal<KnownRootsSource, readonly string[]>({
    source: () => ({ server: this.server(), roots: this.shown()?.roots }),
    computation: ({ server, roots }, previous) =>
      roots ?? (previous !== undefined && previous.source.server === server ? previous.value : []),
  });

  readonly roots = computed(() => this.knownRoots());

  readonly folder = computed(() => this.shown()?.path ?? this.requested());

  readonly root = computed(() => {
    // Read first: a linkedSignal keeps only what it last computed, so the roots must be computed
    // while a listing is on screen to still be known once the next folder is loading.
    const roots = this.roots();
    const listing = this.shown();
    if (listing !== undefined) {
      return listing.root;
    }
    const folder = this.folder();
    return folder === null ? null : rootOf(folder, roots);
  });

  readonly trail = computed<readonly Crumb[]>(() => {
    const root = this.root();
    const folder = this.folder();
    return root === null || folder === null ? [] : trailOf(root, folder);
  });

  goToPage(page: number, pageSize: number): void {
    this.pageSize.set(pageSize);
    this.page.set(page);
  }

  reload(): void {
    this.listResource.reload();
  }

  downloadUrl(entry: Entry): string {
    const server = this.server();
    return server === null ? '' : this.api.downloadUrl(server, entry.path);
  }

  private readonly uploads = signal<readonly Upload[]>([]);

  private readonly uploadRequests = new Map<string, Subscription>();

  readonly upload = computed(() => {
    const server = this.server();
    return this.uploads().find((upload) => upload.server === server) ?? null;
  });

  readonly uploading = computed(() => this.upload() !== null);

  readonly uploadProgress = computed(() => {
    const upload = this.upload();
    if (upload === null || upload.sent >= upload.total) {
      return null;
    }
    return Math.floor((upload.sent / upload.total) * 100);
  });

  uploadFile(folder: string, file: File): void {
    const server = this.server();
    if (server === null || this.uploads().some((upload) => upload.server === server)) {
      return;
    }
    this.uploads.update((uploads) => [...uploads, { server, folder, name: file.name, sent: 0, total: file.size }]);
    const request = this.api
      .upload(server, folder, file)
      .pipe(
        finalize(() => {
          this.uploadRequests.delete(server);
          this.uploads.update((uploads) => uploads.filter((upload) => upload.server !== server));
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (event) => this.onUploadEvent(server, folder, event),
        error: (error: ApiError) => this.notifyFailure(uploadErrorOf(error), file.name),
      });
    if (!request.closed) {
      this.uploadRequests.set(server, request);
    }
  }

  cancelUpload(): void {
    const server = this.server();
    if (server !== null) {
      this.uploadRequests.get(server)?.unsubscribe();
    }
  }

  private onUploadEvent(server: string, folder: string, event: UploadEvent): void {
    if (event.kind === 'progress') {
      this.uploads.update((uploads) =>
        uploads.map((upload) => (upload.server === server ? { ...upload, sent: event.sent, total: event.total } : upload)),
      );
      return;
    }
    this.reloadIfShowing(server, folder);
    this.toast.add({
      severity: 'success',
      summary: this.locale.translate('files.upload.done'),
      detail: isolated(event.entry.name),
    });
  }

  readonly creating = signal(false);
  readonly createError = signal<ApiError | null>(null);

  resetNewFolder(): void {
    this.createError.set(null);
  }

  async createFolder(folder: string, name: string): Promise<Entry | null> {
    const server = this.server();
    if (server === null) {
      return null;
    }
    this.creating.set(true);
    this.createError.set(null);
    let created: Entry;
    try {
      created = await firstValueFrom(this.api.createFolder(server, { path: folder, name }));
    } catch (error) {
      this.createError.set(error as ApiError);
      return null;
    } finally {
      this.creating.set(false);
    }
    this.reloadIfShowing(server, folder);
    this.toast.add({
      severity: 'success',
      summary: this.locale.translate('files.newFolder.done'),
      detail: isolated(created.name),
    });
    return created;
  }

  private readonly deleting = signal<ReadonlySet<string>>(new Set());

  isDeleting(entry: Entry): boolean {
    const server = this.server();
    return server !== null && this.deleting().has(deletionKey(server, entry));
  }

  async remove(entry: Entry): Promise<boolean> {
    const server = this.server();
    const folder = this.current();
    if (server === null) {
      return false;
    }
    const key = deletionKey(server, entry);
    this.deleting.update((keys) => withItem(keys, key));
    try {
      await firstValueFrom(this.api.remove(server, entry.path));
    } catch (error) {
      this.notifyFailure(error as ApiError, entry.name);
      return false;
    } finally {
      this.deleting.update((keys) => withoutItem(keys, key));
    }
    if (folder !== null) {
      this.afterRemoval(server, folder);
    }
    const done = entry.kind === 'folder' ? 'files.delete.folderDone' : 'files.delete.fileDone';
    this.toast.add({ severity: 'success', summary: this.locale.translate(done), detail: isolated(entry.name) });
    return true;
  }

  private afterRemoval(server: string, folder: string): void {
    if (this.server() !== server || this.current() !== folder) {
      return;
    }
    if (this.entries().length === 1 && this.page() > 0) {
      this.page.update((page) => page - 1);
      return;
    }
    this.listResource.reload();
  }

  private reloadIfShowing(server: string, folder: string): void {
    if (this.server() === server && this.current() === folder) {
      this.listResource.reload();
    }
  }

  private notifyFailure(error: ApiError | string, name: string): void {
    this.toast.add({ severity: 'danger', summary: errorText(this.locale, error), detail: isolated(name) });
  }
}

// FSI ... PDI: a name keeps its own direction inside a line of either language.
function isolated(text: string): string {
  return `⁨${text}⁩`;
}

function uploadErrorOf(error: ApiError): ApiError | string {
  return error.fields?.['file']?.[0] ?? error.fields?.['path']?.[0] ?? error;
}

function deletionKey(server: string, entry: Entry): string {
  return `${server}\n${entry.path}`;
}

function withItem(items: ReadonlySet<string>, item: string): ReadonlySet<string> {
  return new Set(items).add(item);
}

function withoutItem(items: ReadonlySet<string>, item: string): ReadonlySet<string> {
  const rest = new Set(items);
  rest.delete(item);
  return rest;
}
