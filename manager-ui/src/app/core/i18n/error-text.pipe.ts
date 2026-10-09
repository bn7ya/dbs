import { Pipe, inject, type PipeTransform } from '@angular/core';

import type { ApiError } from '@core/http/api.types';
import type { ErrorSource } from './error-text.pipe.types';
import { LocaleStore } from './locale.store';

export const GENERIC_ERROR_KEY = 'errors.generic';

// DRF's `fields` key for a validation error that names no field.
const GENERAL_FIELD = 'non_field_errors';

export function errorKey(error: ApiError | string, has: (key: string) => boolean): string {
  const key = `errors.${typeof error === 'string' ? error : summaryCode(error)}`;
  return has(key) ? key : GENERIC_ERROR_KEY;
}

export function errorText(locale: LocaleStore, error: ErrorSource): string {
  if (!error) {
    return '';
  }
  return locale.translate(errorKey(error, (key) => locale.has(key)));
}

function summaryCode(error: ApiError): string {
  const fields = error.fields ?? {};
  const general = fields[GENERAL_FIELD];
  if (general && general.length > 0) {
    return general[0];
  }
  return Object.keys(fields).length > 0 ? 'checkFields' : error.code;
}

@Pipe({ name: 'errorText', pure: false })
export class ErrorTextPipe implements PipeTransform {
  private readonly locale = inject(LocaleStore);

  transform(error: ErrorSource): string {
    return errorText(this.locale, error);
  }
}
