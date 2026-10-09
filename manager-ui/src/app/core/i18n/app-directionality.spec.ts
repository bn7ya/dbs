import { Directionality } from '@angular/cdk/bidi';
import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AppDirectionality } from './app-directionality';
import { AppPaginatorIntl } from './app-paginator-intl';
import { LocaleStore } from './locale.store';

describe('runtime language for Material', () => {
  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [{ provide: Directionality, useExisting: AppDirectionality }, AppPaginatorIntl],
    });
  });

  afterEach(() => {
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it('follows the language switch, so overlays open in the new direction', () => {
    const direction = TestBed.inject(Directionality);
    const changes = vi.fn();
    direction.change.subscribe(changes);
    expect(direction.value).toBe('ltr');

    TestBed.inject(LocaleStore).setLocale('ar');
    TestBed.tick();

    expect(direction.value).toBe('rtl');
    expect(changes).toHaveBeenCalledWith('rtl');
  });

  it('labels the paginator in the reader language and says the range shown', () => {
    const intl = TestBed.inject(AppPaginatorIntl);
    TestBed.tick();
    expect(intl.itemsPerPageLabel).toBe('Rows per page');
    expect(intl.getRangeLabel(1, 20, 45)).toBe('21–40 of 45');
    expect(intl.getRangeLabel(0, 20, 0)).toBe('0–0 of 0');

    const changes = vi.fn();
    intl.changes.subscribe(changes);
    TestBed.inject(LocaleStore).setLocale('ar');
    TestBed.tick();

    expect(intl.nextPageLabel).toBe('الصفحة التالية');
    expect(intl.getRangeLabel(2, 20, 45)).toBe('41–45 من 45');
    expect(changes).toHaveBeenCalled();
  });
});
