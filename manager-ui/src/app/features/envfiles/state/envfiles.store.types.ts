import type { ApiError, Page } from '@core/http/api.types';
import type { EnvListQuery, EnvVersion } from '../data/envfiles.types';

export interface ShownPage {
  readonly query: EnvListQuery;
  readonly page: Page<EnvVersion>;
}

export interface ShownSource {
  readonly query: EnvListQuery | undefined;
  readonly page: Page<EnvVersion> | undefined;
}

export interface Revealed {
  readonly of: string;
  readonly content: string;
}

export interface CompareFailure {
  readonly of: string;
  readonly error: ApiError;
}
