import type { Signal } from '@angular/core';

import type { ApiError } from '@core/http/api.types';

export interface PasswordPromptData {
  readonly titleKey: string;
  readonly bodyKey: string;
  readonly submitKey: string;
  readonly submit: (password: string) => Promise<boolean>;
  readonly error: Signal<ApiError | null>;
}
