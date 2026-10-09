import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { StatusPage } from '@shared/status-page/status-page';
import { LocaleStore } from './locale.store';

describe('TranslatePipe', () => {
  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({ providers: [provideRouter([])] });
  });

  afterEach(() => TestBed.resetTestingModule());

  // Guards the pure-pipe regression: a language switch handed back the string cached in the old one.
  it('re-renders in the new language when the locale changes', async () => {
    const locale = TestBed.inject(LocaleStore);
    locale.setLocale('en');
    const fixture = TestBed.createComponent(StatusPage);
    fixture.componentRef.setInput('titleKey', 'errors.notFound');
    fixture.componentRef.setInput('bodyKey', 'errors.notFoundBody');
    const heading = (): string => (fixture.nativeElement as HTMLElement).querySelector('h1')?.textContent?.trim() ?? '';

    await fixture.whenStable();
    expect(heading()).toBe('Page not found.');

    locale.setLocale('ar');
    await fixture.whenStable();
    expect(heading()).toBe('الصفحة غير موجودة.');

    locale.setLocale('en');
    await fixture.whenStable();
    expect(heading()).toBe('Page not found.');
  });
});
