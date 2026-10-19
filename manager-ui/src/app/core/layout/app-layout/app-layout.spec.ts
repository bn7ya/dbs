import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthStore } from '@core/auth/state/auth.store';
import { LocaleStore } from '@core/i18n/locale.store';
import { AppLayout } from './app-layout';

describe('AppLayout', () => {
  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
        {
          provide: AuthStore,
          useValue: { displayName: signal('admin'), busy: signal(false), can: () => true, signOut: vi.fn() },
        },
      ],
    });
    TestBed.inject(LocaleStore);
  });

  afterEach(() => {
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it('has one navigation landmark, named, holding every section', async () => {
    const fixture = TestBed.createComponent(AppLayout);
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;

    const landmarks = host.querySelectorAll('nav, [role="navigation"]');

    expect(landmarks).toHaveLength(1);
    expect(landmarks[0].getAttribute('aria-label')).toBe('Main');
    expect([...landmarks[0].querySelectorAll('a')].map((link) => link.textContent?.trim())).toEqual([
      'Dashboard',
      'Servers',
      'Applications',
      'Backups',
      'Console',
      'Activity',
      'Accounts',
    ]);
  });
});
