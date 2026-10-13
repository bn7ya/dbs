import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { LocaleStore } from '@core/i18n/locale.store';
import { ConnectionDot } from './connection-dot';

describe('ConnectionDot', () => {
  let fixture: ComponentFixture<ConnectionDot>;

  const host = (): HTMLElement => {
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  };
  const text = (): string => host().textContent?.replace(/\s+/g, ' ').trim() ?? '';

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-10-09T12:00:00Z'));
    localStorage.setItem('locale', 'en');
    fixture = TestBed.createComponent(ConnectionDot);
  });

  afterEach(() => {
    vi.useRealTimers();
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it('names the state beside its dot, never by colour alone', () => {
    fixture.componentRef.setInput('state', 'online');
    fixture.componentRef.setInput('lastSeenAt', '2026-10-09T11:59:00Z');

    expect(text()).toBe('Online');
    expect(host().classList).toContain('connection-dot--online');
    expect(host().querySelector('i')?.getAttribute('aria-hidden')).toBe('true');

    fixture.componentRef.setInput('state', 'unknown');
    expect(text()).toBe('Not seen yet');
  });

  it('says when an offline server was last seen, in Arabic too', () => {
    fixture.componentRef.setInput('state', 'offline');
    fixture.componentRef.setInput('lastSeenAt', '2026-10-09T09:00:00Z');

    expect(text()).toBe('Offline, last seen 3 hours ago');
    TestBed.inject(LocaleStore).setLocale('ar');
    expect(text()).toContain('غير متصل');
  });
});
