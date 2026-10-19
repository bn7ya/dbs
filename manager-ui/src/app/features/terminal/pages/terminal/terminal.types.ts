import type { ApiError } from '@core/http/api.types';
import type { NoticeSeverity } from '@shared/notice/notice.types';

export interface TranslatedLine {
  readonly key: string;
  readonly values?: Readonly<Record<string, string | number>>;
}

export interface EndNotice {
  readonly severity: NoticeSeverity;
  readonly line: TranslatedLine | null;
  readonly error: ApiError | null;
}
