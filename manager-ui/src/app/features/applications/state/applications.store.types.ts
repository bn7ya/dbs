import type { Page } from '@core/http/api.types';
import type { ApplicationSummary } from '../data/applications.types';

export interface ListScope {
  readonly server: string | null;
}

export interface ShownList {
  readonly open: boolean;
  readonly page: Page<ApplicationSummary> | undefined;
}
