import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { LocaleStore } from '@core/i18n/locale.store';
import { JobConnection } from './job-connection';

describe('JobConnection', () => {
  let fixture: ComponentFixture<JobConnection>;

  const text = (): string => {
    fixture.detectChanges();
    return (fixture.nativeElement as HTMLElement).textContent?.replace(/\s+/g, ' ').trim() ?? '';
  };

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-10-09T12:00:00Z'));
    localStorage.setItem('locale', 'en');
    fixture = TestBed.createComponent(JobConnection);
  });

  afterEach(() => {
    vi.useRealTimers();
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it('says the connection is alive, how much moved and when the server last answered', () => {
    fixture.componentRef.setInput('connection', {
      state: 'alive',
      last_activity_at: '2026-10-09T11:58:00Z',
      bytes: 5_200_000,
    });

    expect(text()).toBe('Connection alive 5.2 MB moved, last heard 2 minutes ago');
    expect((fixture.nativeElement as HTMLElement).getAttribute('role')).toBe('status');
  });

  it('says when the connection was lost, in Arabic too', () => {
    fixture.componentRef.setInput('connection', {
      state: 'lost',
      last_activity_at: '2026-10-09T11:58:00Z',
      bytes: 0,
    });

    expect(text()).toContain('Connection lost');
    TestBed.inject(LocaleStore).setLocale('ar');
    expect(text()).toContain('انقطع الاتصال');
  });
});
