import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { afterEach, describe, expect, it } from 'vitest';

import { LocaleStore } from '@core/i18n/locale.store';
import { LOCAL_TIME_ZONE } from '../../data/zoned-time';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { NextRun } from './next-run';

describe('NextRun', () => {
  let fixture: ComponentFixture<NextRun>;

  const show = (at: string, zone: string, local = 'UTC'): HTMLElement => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({ providers: [{ provide: LOCAL_TIME_ZONE, useValue: local }] });
    TestBed.inject(LocaleStore).register({ en, ar });
    fixture = TestBed.createComponent(NextRun);
    fixture.componentRef.setInput('at', at);
    fixture.componentRef.setInput('zone', zone);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  };

  const spaced = (text: string | null | undefined) => (text ?? '').replace(/\s+/g, ' ').trim();

  afterEach(() => {
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it("shows the run in the plan's zone, names the zone, and adds the reader's own time when it differs", () => {
    const view = show('2026-10-01T23:00:00Z', 'Asia/Riyadh');

    const time = view.querySelector('time');
    expect(time?.getAttribute('datetime')).toBe('2026-10-01T23:00:00Z');
    expect(spaced(time?.textContent)).toBe('Oct 2, 2026, 2:00 AM');
    const zone = view.querySelector('bdi');
    expect(zone?.textContent).toBe('Asia/Riyadh');
    expect(zone?.getAttribute('dir')).toBe('ltr');
    expect(spaced(view.textContent)).toContain('Your time: Oct 1, 2026, 11:00 PM');
  });

  it("leaves the reader's time out when it reads the same", () => {
    const view = show('2026-10-01T23:00:00Z', 'Europe/London', 'Europe/Dublin');

    expect(view.textContent).not.toContain('Your time');
  });

  it('follows a language switch, with Latin digits in Arabic', () => {
    const view = show('2026-10-01T23:00:00Z', 'Asia/Riyadh');

    TestBed.inject(LocaleStore).setLocale('ar');
    fixture.detectChanges();

    expect(view.querySelector('time')?.textContent).toMatch(/2026/);
    expect(view.textContent).toContain('بتوقيتك:');
  });
});
