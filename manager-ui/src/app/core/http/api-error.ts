import type { ApiError } from './api.types';

export function apiErrorOf(error: Error | undefined): ApiError | null {
  if (!error) {
    return null;
  }
  const cause: unknown = error.cause ?? error;
  return isApiError(cause) ? cause : { code: 'unknown', message: '' };
}

function isApiError(value: unknown): value is ApiError {
  return typeof value === 'object' && value !== null && typeof (value as ApiError).code === 'string';
}
