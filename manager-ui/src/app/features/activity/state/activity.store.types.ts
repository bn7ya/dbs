import type { Page } from '@core/http/api.types';
import type { ActivityEntry, ActivityStatus } from '../data/activity.types';

export type ActivityStatusFilter = ActivityStatus | '';

export type ActivityScope =
  | { readonly kind: 'all' }
  | { readonly kind: 'server'; readonly id: string }
  | { readonly kind: 'application'; readonly id: string };

export interface ShownPageSource {
  readonly open: boolean;
  readonly page: Page<ActivityEntry> | undefined;
}
