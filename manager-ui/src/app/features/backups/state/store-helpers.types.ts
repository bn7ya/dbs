import type { Page } from '@core/http/api.types';

export interface ShownPage<T> {
  readonly key: string | null;
  readonly page: Page<T> | undefined;
}
