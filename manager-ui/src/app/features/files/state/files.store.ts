import { DestroyRef, Injectable, computed, inject, linkedSignal, signal } from '@angular/core';
import { rxResource, takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { finalize, firstValueFrom, type Subscription } from 'rxjs';

import { apiErrorOf } from '@core/http/api-error';
import type { ApiError } from '@core/http/api.types';
import { errorText } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { isolated } from '@shared/isolated/isolated';
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

  readonly application = signal<string | null>(null);

  readonly requested = signal<string | null>(null);

  show(application: string, path: string | null): void {
    this.application.set(application);
    this.requested.set(path);
    this.page.set(0);
    this.isOpen.set(true);
  }

  close(): void {
    this.isOpen.set(false);
  }

  readonly page = linkedSignal({
    source: () => `${this.application()}\n${this.requested()}`,
    computation: () => 0,
  });
  readonly pageSize = signal(FILE_PAGE_SIZES[0]);

  private readonly query = computed<ListingQuery | undefined>(() => {
    const application = this.isOpen() ? this.application() : null;
    return application === null
      ? undefined
      : { application, path: this.requested(), page: this.page() + 1, page_size: this.pageSize() };
  });

  private readonly listResource = rxResource({
    params: () => this.query(),
    stream: ({ params }) => this.api.list(params),
  });

  private readonly shown = linkedSignal<ShownSource, Listing | undefined>({
    source: () => {
      const query = this.query();
      return {
        place: query === undefined ? null : `${query.application}\n${query.path}`,
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
    source: () => ({ application: this.application(), roots: this.shown()?.roots }),
    computation: ({ application, roots }, previous) =>
      roots ?? (previous !== undefined && previous.source.application === application ? previous.value : []),
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

  readonly downloadError = signal<ApiError | null>(null);

  readonly downloadNeedsPassword = computed(() => asksForPassword(this.downloadError()));

  private readonly preparing = signal<ReadonlySet<string>>(new Set());

  isPreparing(entry: Entry): boolean {
    const application = this.application();
    return application !== null && this.preparing().has(entryKey(application, entry));
  }

  // Asked without a password, a refusal that wants one is the prompt's to show; any other is said here.
  async downloadLink(entry: Entry, password = ''): Promise<string | null> {
    const application = this.application();
    if (application === null) {
      return null;
    }
    const key = entryKey(application, entry);
    this.preparing.update((keys) => withItem(keys, key));
    this.downloadError.set(null);
    try {
      const { url } = await firstValueFrom(this.api.downloadLink(application, entry.path, password));
      return url;
    } catch (error) {
      const failure = error as ApiError;
      this.downloadError.set(failure);
      if (password === '' && !asksForPassword(failure)) {
        this.notifyFailure(failure, entry.name);
      }
      return null;
    } finally {
      this.preparing.update((keys) => withoutItem(keys, key));
    }
  }

  private readonly uploads = signal<readonly Upload[]>([]);

  private readonly uploadRequests = new Map<string, Subscription>();

  readonly upload = computed(() => {
    const application = this.application();
    return this.uploads().find((upload) => upload.application === application) ?? null;
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
    const application = this.application();
    if (application === null || this.uploads().some((upload) => upload.application === application)) {
      return;
    }
    this.uploads.update((uploads) => [...uploads, { application, folder, name: file.name, sent: 0, total: file.size }]);
    const request = this.api
      .upload(application, folder, file)
      .pipe(
        finalize(() => {
          this.uploadRequests.delete(application);
          this.uploads.update((uploads) => uploads.filter((upload) => upload.application !== application));
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (event) => this.onUploadEvent(application, folder, event),
        error: (error: ApiError) => this.notifyFailure(uploadErrorOf(error), file.name),
      });
    if (!request.closed) {
      this.uploadRequests.set(application, request);
    }
  }

  cancelUpload(): void {
    const application = this.application();
    if (application !== null) {
      this.uploadRequests.get(application)?.unsubscribe();
    }
  }

  private onUploadEvent(application: string, folder: string, event: UploadEvent): void {
    if (event.kind === 'progress') {
      this.uploads.update((uploads) =>
        uploads.map((upload) => (upload.application === application ? { ...upload, sent: event.sent, total: event.total } : upload)),
      );
      return;
    }
    this.reloadIfShowing(application, folder);
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
    const application = this.application();
    if (application === null) {
      return null;
    }
    this.creating.set(true);
    this.createError.set(null);
    let created: Entry;
    try {
      created = await firstValueFrom(this.api.createFolder(application, { path: folder, name }));
    } catch (error) {
      this.createError.set(error as ApiError);
      return null;
    } finally {
      this.creating.set(false);
    }
    this.reloadIfShowing(application, folder);
    this.toast.add({
      severity: 'success',
      summary: this.locale.translate('files.newFolder.done'),
      detail: isolated(created.name),
    });
    return created;
  }

  private readonly deleting = signal<ReadonlySet<string>>(new Set());

  isDeleting(entry: Entry): boolean {
    const application = this.application();
    return application !== null && this.deleting().has(entryKey(application, entry));
  }

  async remove(entry: Entry): Promise<boolean> {
    const application = this.application();
    const folder = this.current();
    if (application === null) {
      return false;
    }
    const key = entryKey(application, entry);
    this.deleting.update((keys) => withItem(keys, key));
    try {
      await firstValueFrom(this.api.remove(application, entry.path));
    } catch (error) {
      this.notifyFailure(error as ApiError, entry.name);
      return false;
    } finally {
      this.deleting.update((keys) => withoutItem(keys, key));
    }
    if (folder !== null) {
      this.afterRemoval(application, folder);
    }
    const done = entry.kind === 'folder' ? 'files.delete.folderDone' : 'files.delete.fileDone';
    this.toast.add({ severity: 'success', summary: this.locale.translate(done), detail: isolated(entry.name) });
    return true;
  }

  private afterRemoval(application: string, folder: string): void {
    if (this.application() !== application || this.current() !== folder) {
      return;
    }
    if (this.entries().length === 1 && this.page() > 0) {
      this.page.update((page) => page - 1);
      return;
    }
    this.listResource.reload();
  }

  private reloadIfShowing(application: string, folder: string): void {
    if (this.application() === application && this.current() === folder) {
      this.listResource.reload();
    }
  }

  private notifyFailure(error: ApiError | string, name: string): void {
    this.toast.add({ severity: 'danger', summary: errorText(this.locale, error), detail: isolated(name) });
  }
}

function uploadErrorOf(error: ApiError): ApiError | string {
  return error.fields?.['file']?.[0] ?? error.fields?.['path']?.[0] ?? error;
}

function entryKey(application: string, entry: Entry): string {
  return `${application}\n${entry.path}`;
}

function asksForPassword(failure: ApiError | null): boolean {
  return (failure?.fields?.['account_password'] ?? []).length > 0;
}

function withItem(items: ReadonlySet<string>, item: string): ReadonlySet<string> {
  return new Set(items).add(item);
}

function withoutItem(items: ReadonlySet<string>, item: string): ReadonlySet<string> {
  const rest = new Set(items);
  rest.delete(item);
  return rest;
}
