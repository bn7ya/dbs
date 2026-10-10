import { Injectable, computed, inject, linkedSignal, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';

import { apiErrorOf } from '@core/http/api-error';
import { ServersApi } from '../data/servers.api';
import type { BrowseQuery, RemoteEntry, RemoteFolder } from '../data/servers.types';
import type { BrowserCrumb, BrowserShownSource } from './server-browser.store.types';

export const BROWSER_PAGE_SIZES: readonly number[] = [50, 100, 200];

@Injectable()
export class ServerBrowserStore {
  private readonly api = inject(ServersApi);

  readonly server = signal<string | null>(null);
  readonly requested = signal<string | null>(null);

  readonly page = linkedSignal({
    source: () => `${this.server()}\n${this.requested()}`,
    computation: () => 0,
  });
  readonly pageSize = signal(BROWSER_PAGE_SIZES[0]);

  private readonly query = computed<BrowseQuery | undefined>(() => {
    const server = this.server();
    return server === null
      ? undefined
      : { server, path: this.requested(), page: this.page() + 1, page_size: this.pageSize() };
  });

  private readonly folderResource = rxResource({
    params: () => this.query(),
    stream: ({ params }) => this.api.browse(params),
  });

  private readonly shown = linkedSignal<BrowserShownSource, RemoteFolder | undefined>({
    source: () => {
      const query = this.query();
      return {
        place: query === undefined ? null : `${query.server}\n${query.path}`,
        folder: this.folderResource.hasValue() ? this.folderResource.value() : undefined,
      };
    },
    computation: ({ place, folder }, previous) =>
      folder ?? (place !== null && place === previous?.source.place ? previous.value : undefined),
  });

  readonly path = computed(() => this.shown()?.path ?? null);
  readonly entries = computed<readonly RemoteEntry[]>(() => this.shown()?.results ?? []);
  readonly count = computed(() => this.shown()?.count ?? 0);
  readonly isProject = computed(() => this.shown()?.project ?? false);
  readonly truncated = computed(() => this.shown()?.truncated ?? false);
  readonly loading = this.folderResource.isLoading;
  readonly error = computed(() => apiErrorOf(this.folderResource.error()));
  readonly pending = computed(() => this.shown() === undefined && this.loading());
  readonly empty = computed(() => this.shown()?.count === 0);

  readonly trail = computed<readonly BrowserCrumb[]>(() => {
    const path = this.path();
    return path === null ? [] : trailOf(path);
  });

  open(server: string, path: string | null): void {
    this.server.set(server);
    this.requested.set(path);
  }

  go(path: string | null): void {
    this.requested.set(path);
  }

  up(): void {
    const parent = this.shown()?.parent;
    if (parent) {
      this.requested.set(parent);
    }
  }

  home(): void {
    this.requested.set(this.shown()?.home ?? null);
  }

  goToPage(page: number, pageSize: number): void {
    this.pageSize.set(pageSize);
    this.page.set(page);
  }

  reload(): void {
    this.folderResource.reload();
  }
}

export function trailOf(path: string): readonly BrowserCrumb[] {
  const trail: BrowserCrumb[] = [{ path: '/', name: '/' }];
  let current = '';
  for (const name of path.split('/').filter((step) => step !== '')) {
    current = `${current}/${name}`;
    trail.push({ path: current, name });
  }
  return trail;
}
