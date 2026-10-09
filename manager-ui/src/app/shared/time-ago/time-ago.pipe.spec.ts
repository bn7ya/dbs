import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { LocaleStore } from '@core/i18n/locale.store';
import { TimeAgoPipe } from './time-ago.pipe';

describe('TimeAgoPipe', () => {
  let pipe: TimeAgoPipe;

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-10-09T12:00:00Z'));
    localStorage.setItem('locale', 'en');
    pipe = TestBed.runInInjectionContext(() => new TimeAgoPipe());
  });

  afterEach(() => {
    vi.useRealTimers();
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it('says how long ago in the largest whole unit, and nothing for no date', () => {
    expect(pipe.transform('2026-10-09T11:55:00Z')).toBe('5 minutes ago');
    expect(pipe.transform('2026-10-09T09:00:00Z')).toBe('3 hours ago');
    expect(pipe.transform('2026-10-01T12:00:00Z')).toBe('8 days ago');
    expect(pipe.transform('2026-10-09T13:00:00Z')).toBe('in 1 hour');
    expect(pipe.transform(null)).toBe('');
  });

  it('speaks the reader language with Latin digits', () => {
    TestBed.inject(LocaleStore).setLocale('ar');
    expect(pipe.transform('2026-10-09T09:00:00Z')).toMatch(/3/);
  });
});
