import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { provideRouter } from '@angular/router';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import { Toaster } from '@shared/toaster/toaster';
import type { BackupPlan } from '../../data/plans.types';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { PlansStore } from '../../state/plans.store';
import { RIYADH_PLAN } from '../../testing/backups.fixtures';
import { RescheduleForm } from './reschedule-form';

describe('RescheduleForm', () => {
  let http: HttpTestingController;
  let close: ReturnType<typeof vi.fn>;
  let fixture: ComponentFixture<RescheduleForm>;

  const open = (plan: BackupPlan = RIYADH_PLAN): RescheduleForm => {
    close = vi.fn();
    localStorage.setItem('locale', 'en');
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-10-01T00:00:00Z'));
    TestBed.configureTestingModule({
      providers: [
        PlansStore,
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: MatDialogRef, useValue: { close } },
        { provide: MAT_DIALOG_DATA, useValue: { data: { plan } } },
        { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
      ],
    });
    TestBed.inject(LocaleStore).register({ en, ar });
    vi.spyOn(TestBed.inject(Toaster), 'add').mockReturnValue(undefined);
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(RescheduleForm);
    return fixture.componentInstance;
  };

  const rendered = (): HTMLElement => {
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  };

  const rescheduleRequest = () => http.expectOne(`/api/backups/plans/${RIYADH_PLAN.id}/reschedule/`);

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("starts from the plan's next run as its own zone's wall clock, and says which zone", () => {
    const form = open();

    const { day, time } = form.moment();
    expect([day?.getFullYear(), day?.getMonth(), day?.getDate()]).toEqual([2026, 9, 2]);
    expect([time?.getHours(), time?.getMinutes()]).toEqual([2, 0]);
    const text = rendered().textContent ?? '';
    expect(text).toContain(`Choose when ⁨${RIYADH_PLAN.name}⁩ runs next.`);
    expect(text).toContain('In ⁨Asia/Riyadh⁩, within a year.');
  });

  it("sends the moment chosen in the plan's zone, then closes with the plan", async () => {
    const form = open();
    form.setDay(new Date(2026, 9, 5));
    form.setTime(new Date(2026, 9, 5, 4, 30));

    const saving = form.save();
    const request = rescheduleRequest();
    expect(request.request.body).toEqual({ next_run_at: '2026-10-05T04:30:00+03:00' });
    const moved = { ...RIYADH_PLAN, next_run_at: '2026-10-05T01:30:00Z' };
    request.flush(moved);
    await saving;

    expect(close).toHaveBeenCalledWith(moved);
  });

  it('asks for a date and a time after now and within a year before it sends anything', async () => {
    const form = open({ ...RIYADH_PLAN, next_run_at: null });
    expect(form.moment()).toEqual({ day: null, time: null });

    await form.save();
    http.expectNone(`/api/backups/plans/${RIYADH_PLAN.id}/reschedule/`);
    expect(form.errorFor('day')).toBe('Fill in this field.');

    form.setDay(new Date(2026, 8, 1));
    form.setTime(new Date(2026, 8, 1, 4, 0));
    expect(form.errorFor('day')).toBe('Choose a moment after now and within a year.');
    expect(rendered().querySelector('mat-error')?.textContent?.trim()).toBe('Choose a moment after now and within a year.');

    form.setDay(new Date(2026, 9, 1));
    form.setTime(null);
    expect(form.errorFor('time')).toBe('Fill in this field.');
  });

  it("shows the backend's refusal of the moment under the date, and a refusal of the plan above the form", async () => {
    const form = open();

    const saving = form.save();
    rescheduleRequest().flush(
      { error: { code: 'invalid', message: 'Server prose', fields: { next_run_at: ['invalid_moment'] } } },
      { status: 400, statusText: 'Bad Request' },
    );
    await saving;
    expect(close).not.toHaveBeenCalled();
    expect(form.errorFor('day')).toBe('Choose a moment after now and within a year.');
    expect(form.formFailure()).toBeNull();

    form.setTime(new Date(2026, 9, 2, 3, 0));
    expect(form.errorFor('day')).toBe('');

    const again = form.save();
    rescheduleRequest().flush(
      { error: { code: 'invalid', message: 'Server prose', fields: { interval_minutes: ['manual_plan'] } } },
      { status: 400, statusText: 'Bad Request' },
    );
    await again;
    expect(form.formFailure()).toBe('manual_plan');
    expect(rendered().querySelector('app-notice')?.textContent).toContain(
      'This plan runs only from Run now. Give it a schedule first.',
    );
  });
});
