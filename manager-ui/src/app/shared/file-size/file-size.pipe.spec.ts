import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { LocaleStore } from '@core/i18n/locale.store';
import { FileSizePipe } from './file-size.pipe';

describe('FileSizePipe', () => {
  let pipe: FileSizePipe;

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    // The locale store is what tells the library's formatter which language is on screen.
    TestBed.inject(LocaleStore);
    pipe = TestBed.runInInjectionContext(() => new FileSizePipe());
  });

  afterEach(() => {
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it("writes a size the way the reader's language does", () => {
    expect(pipe.transform(0)).toBe('0 bytes');
    expect(pipe.transform(512)).toBe('512 bytes');
    expect(pipe.transform(1_200_000)).toBe('1.2 MB');
    expect(pipe.transform(1_500_000_000)).toBe('1.5 GB');
    expect(pipe.transform(2_000_000_000_000_000)).toBe('2,000 TB');

    TestBed.inject(LocaleStore).setLocale('ar');
    TestBed.tick();
    expect(pipe.transform(1_200_000)).toBe('1.2 م.ب');
  });
});
