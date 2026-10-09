import { EnvironmentInjector, createEnvironmentInjector } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { LocaleStore } from './locale.store';
import { provideTranslations } from './provide-translations';

describe('provideTranslations', () => {
  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({});
  });

  afterEach(() => TestBed.resetTestingModule());

  it('registers a bundle when the route injector that provides it is created', () => {
    const store = TestBed.inject(LocaleStore);
    store.setLocale('ar');
    TestBed.tick();
    expect(store.translate('orders.title')).toBe('orders.title');

    createEnvironmentInjector(
      [provideTranslations({ orders: { title: 'Orders' } }, { orders: { title: 'الطلبات' } })],
      TestBed.inject(EnvironmentInjector),
    );

    expect(store.translate('orders.title')).toBe('الطلبات');
  });
});
