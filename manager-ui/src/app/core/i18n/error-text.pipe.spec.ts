import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { ApiError } from '@core/http/api.types';
import { ErrorTextPipe, GENERIC_ERROR_KEY, errorKey, errorText } from './error-text.pipe';
import { LocaleStore } from './locale.store';

const known = (key: string): boolean => ['errors.invalid_password', 'errors.required'].includes(key);

describe('errorKey', () => {
  it('resolves a code to its errors.<code> key', () => {
    expect(errorKey({ code: 'invalid_password', message: 'ignored' }, known)).toBe('errors.invalid_password');
  });

  it('falls back to the generic message for a code no bundle has yet', () => {
    expect(errorKey({ code: 'brand_new', message: 'ignored' }, known)).toBe(GENERIC_ERROR_KEY);
  });

  it('points at the fields when the error is about fields', () => {
    const error: ApiError = { code: 'invalid', message: 'ignored', fields: { name: ['name_taken'] } };
    expect(errorKey(error, (key) => key === 'errors.checkFields')).toBe('errors.checkFields');
  });

  it('says a general validation error itself, since no field can hold it', () => {
    const error: ApiError = { code: 'invalid', message: 'ignored', fields: { non_field_errors: ['required'] } };
    expect(errorKey(error, known)).toBe('errors.required');
  });

  it('resolves a bare field code the same way', () => {
    expect(errorKey('required', known)).toBe('errors.required');
  });
});

describe('errorText', () => {
  let locale: LocaleStore;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({});
    locale = TestBed.inject(LocaleStore);
    locale.setLocale('en');
    TestBed.tick();
  });

  afterEach(() => TestBed.resetTestingModule());

  it('never prints the message the backend sent', () => {
    const error: ApiError = { code: 'invalid_password', message: 'Server prose' };

    expect(errorText(locale, error)).toBe('The password is not correct.');
  });

  it('reads in the language on screen', () => {
    locale.setLocale('ar');
    TestBed.tick();

    expect(errorText(locale, 'required')).toBe('املأ هذا الحقل.');
  });

  it('says nothing for no error', () => {
    expect(errorText(locale, null)).toBe('');
  });

  it('is what the pipe renders', () => {
    const pipe = TestBed.runInInjectionContext(() => new ErrorTextPipe());

    expect(pipe.transform({ code: 'nope', message: 'Server prose' })).toBe('Something went wrong. Try again.');
  });
});

describe('LocaleStore.has', () => {
  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({});
  });

  afterEach(() => TestBed.resetTestingModule());

  it('knows which keys resolve, where translate would echo the key back', () => {
    const locale = TestBed.inject(LocaleStore);

    expect(locale.has('errors.generic')).toBe(true);
    expect(locale.has('errors.nothing_here')).toBe(false);
  });
});
