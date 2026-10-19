import { linkedSignal, type ResourceRef, type Signal } from '@angular/core';

import type { Page } from '@core/http/api.types';
import type { ShownPage } from './store-helpers.types';

// Paging keeps the rows on screen until the next page arrives; another list never shows the last one's.
export function shownPageOf<T>(
  key: Signal<string | null>,
  resource: ResourceRef<Page<T> | undefined>,
): Signal<Page<T> | undefined> {
  return linkedSignal<ShownPage<T>, Page<T> | undefined>({
    source: () => ({ key: key(), page: resource.hasValue() ? resource.value() : undefined }),
    computation: ({ key, page }, previous) =>
      page ?? (key !== null && key === previous?.source.key ? previous.value : undefined),
  });
}

export function withItem(items: ReadonlySet<string>, item: string): ReadonlySet<string> {
  return new Set(items).add(item);
}

export function withoutItem(items: ReadonlySet<string>, item: string): ReadonlySet<string> {
  const rest = new Set(items);
  rest.delete(item);
  return rest;
}

export function withoutKey<V>(entries: ReadonlyMap<number, V>, key: number): ReadonlyMap<number, V> {
  const rest = new Map(entries);
  rest.delete(key);
  return rest;
}
