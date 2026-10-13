import type { Signal } from '@angular/core';

import type { ApiError } from '@core/http/api.types';

export interface PasswordPromptData {
  readonly titleKey: string;
  readonly bodyKey: string;
  readonly bodyValues?: Readonly<Record<string, string | number>>;
  readonly submitKey: string;
  readonly destructive?: boolean;
  readonly submit: (password: string) => Promise<boolean>;
  readonly error: Signal<ApiError | null>;
}
