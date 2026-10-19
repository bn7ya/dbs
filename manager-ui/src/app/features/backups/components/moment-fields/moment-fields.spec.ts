import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { Component, signal } from '@angular/core';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatDatepickerInputHarness } from '@angular/material/datepicker/testing';
import { MatTimepickerInputHarness } from '@angular/material/timepicker/testing';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { LocaleStore } from '@core/i18n/locale.store';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { MomentFields } from './moment-fields';

@Component({
  selector: 'app-host',
  imports: [MomentFields],
  template: `<app-moment-fields
    name="first"
    dayLabel="Date"
    timeLabel="Time"
    hint="When it starts."
    [dayError]="dayError()"
    [(day)]="day"
    [(time)]="time"
  />`,
})
class Host {
  readonly day = signal<Date | null>(null);
  readonly time = signal<Date | null>(null);
  readonly dayError = signal('');
}

describe('MomentFields', () => {
  let fixture: ComponentFixture<Host>;

  const open = (): Host => {
    localStorage.setItem('locale', 'en');
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date(2026, 9, 1, 12, 0));
    TestBed.configureTestingModule({
      providers: [{ provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } }],
    });
    TestBed.inject(LocaleStore).register({ en, ar });
    fixture = TestBed.createComponent(Host);
    fixture.detectChanges();
    return fixture.componentInstance;
  };

  const loader = () => TestbedHarnessEnvironment.loader(fixture);

  afterEach(() => {
    TestBed.resetTestingModule();
    localStorage.clear();
    vi.useRealTimers();
  });

  it('passes the date and the time picked back up, each as a browser date', async () => {
    const host = open();

    await (await loader().getHarness(MatDatepickerInputHarness)).setValue('10/20/2026');
    await (await loader().getHarness(MatTimepickerInputHarness)).setValue('2:30 PM');

    const day = host.day();
    const time = host.time();
    expect([day?.getFullYear(), day?.getMonth(), day?.getDate()]).toEqual([2026, 9, 20]);
    expect([time?.getHours(), time?.getMinutes()]).toEqual([14, 30]);
  });

  it('offers the days from today to a year ahead', async () => {
    open();

    const picker = await loader().getHarness(MatDatepickerInputHarness);
    expect(await picker.getMin()).toBe('2026-10-01');
    expect(await picker.getMax()).toBe('2027-10-02');
  });

  it("names its toggles in the reader's language, and shows the hint and the error it is given", () => {
    const host = open();
    const view = fixture.nativeElement as HTMLElement;

    expect(view.querySelector('mat-datepicker-toggle button')?.getAttribute('aria-label')).toBe('Open the calendar');
    expect(view.querySelector('mat-timepicker-toggle button')?.getAttribute('aria-label')).toBe('Choose a time');
    expect(view.textContent).toContain('When it starts.');
    expect(view.querySelector('input[name="first_day"]')).not.toBeNull();
    expect(view.querySelector('input[name="first_time"]')).not.toBeNull();

    host.dayError.set('Fill in this field.');
    fixture.detectChanges();
    expect(view.querySelector('mat-error')?.textContent?.trim()).toBe('Fill in this field.');

    TestBed.inject(LocaleStore).setLocale('ar');
    fixture.detectChanges();
    expect(view.querySelector('mat-datepicker-toggle button')?.getAttribute('aria-label')).toBe('فتح التقويم');
  });
});
