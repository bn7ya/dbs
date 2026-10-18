import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { MatAutocompleteHarness } from '@angular/material/autocomplete/testing';
import { MatChipGridHarness } from '@angular/material/chips/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatRadioButtonHarness } from '@angular/material/radio/testing';
import { provideRouter } from '@angular/router';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import { Toaster } from '@shared/toaster/toaster';
import { LOCAL_TIME_ZONE } from '../../data/zoned-time';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { PlansStore } from '../../state/plans.store';
import { APPLICATION_ID, ARCHIVE_PLAN, COLLECT_PLAN, MANUAL_PLAN, PLAN } from '../../testing/backups.fixtures';
import { PlanForm } from './plan-form';
import type { PlanFormData } from './plan-form.types';

const PASSWORD = 'correct-horse-battery-staple';

const BROWSER_ZONE = 'Europe/Berlin';

describe('PlanForm', () => {
  let http: HttpTestingController;
  let close: ReturnType<typeof vi.fn>;
  let fixture: ComponentFixture<PlanForm>;

  const open = (data: PlanFormData): PlanForm => {
    close = vi.fn();
    localStorage.setItem('locale', 'en');
    // Only the clock is fixed, so a first run "after now" stays after now.
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-10-01T00:00:00Z'));
    TestBed.configureTestingModule({
      providers: [
        PlansStore,
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: MatDialogRef, useValue: { close } },
        { provide: MAT_DIALOG_DATA, useValue: { data } },
        { provide: LOCAL_TIME_ZONE, useValue: BROWSER_ZONE },
        { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
      ],
    });
    TestBed.inject(LocaleStore).register({ en, ar });
    TestBed.inject(PlansStore).application.set(APPLICATION_ID);
    vi.spyOn(TestBed.inject(Toaster), 'add').mockReturnValue(undefined);
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(PlanForm);
    return fixture.componentInstance;
  };

  const harnesses = TestbedHarnessEnvironment;

  const chipGrids = async (): Promise<number> =>
    (await harnesses.loader(fixture).getAllHarnesses(MatChipGridHarness)).length;

  const radioLabels = async (): Promise<string[]> =>
    Promise.all(
      (await harnesses.loader(fixture).getAllHarnesses(MatRadioButtonHarness)).map((radio) => radio.getLabelText()),
    );

  const rendered = (): HTMLElement => {
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  };

  const input = (view: HTMLElement, name: string): HTMLInputElement | null =>
    view.querySelector<HTMLInputElement>(`input[name="${name}"]`);

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("starts a new plan daily in the browser's time zone, keeping five here and none on the server", () => {
    const form = open({ plan: null, name: 'django-dbs' });

    expect(form.draft()).toEqual({
      kind: 'dbs',
      paths: [],
      folder: '',
      pattern: '*',
      name: 'django-dbs',
      schedule: 'daily',
      firstDay: null,
      firstTime: null,
      timeZone: BROWSER_ZONE,
      keep: 5,
      keep_remote: 0,
      enabled: true,
    });
    expect(form.scheduleOptions().map((option) => option.label)).toEqual([
      'Manual',
      'Every hour',
      'Every 3 hours',
      'Every 6 hours',
      'Every 12 hours',
      'Daily',
      'Weekly',
    ]);
  });

  it('holds the save until the name is filled and the counts are in range, and says why', async () => {
    const form = open({ plan: null });
    expect(form.error('name')).toBeNull();
    form.update('keep', null);
    form.update('keep_remote', 6);

    await form.save();

    http.expectNone('/api/backups/plans/');
    expect(form.error('name')).toBe('required');
    expect(form.error('keep')).toBe('required');
    expect(form.error('keep_remote')).toBe('keep_remote_range');

    form.update('keep', 0);
    expect(form.error('keep')).toBe('keep_range');
    form.update('keep', 6);
    expect(form.error('keep')).toBe('keep_range');
    form.update('keep', 5);
    expect(form.error('keep')).toBeNull();
  });

  it('sends the interval of the schedule chosen and the time zone, without a first run, then closes', async () => {
    const form = open({ plan: null, name: 'django-dbs' });
    form.setSchedule('every6Hours');
    form.update('keep_remote', 2);

    const saving = form.save();
    const request = http.expectOne('/api/backups/plans/');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({
      application: APPLICATION_ID,
      kind: 'dbs',
      name: 'django-dbs',
      interval_minutes: 360,
      keep: 5,
      keep_remote: 2,
      enabled: true,
      paths: [],
      pattern: '',
      time_zone: BROWSER_ZONE,
    });
    request.flush({ ...PLAN, interval_minutes: 360, keep_remote: 2 }, { status: 201, statusText: 'Created' });
    await saving;

    expect(close).toHaveBeenCalledWith({ ...PLAN, interval_minutes: 360, keep_remote: 2 });
  });

  describe('when it first runs', () => {
    it("sends the date and time chosen as that wall clock in the plan's zone, with its offset", async () => {
      const form = open({ plan: null, name: 'django-dbs' });
      form.update('timeZone', 'Asia/Kolkata');
      form.update('firstDay', new Date(2026, 9, 20));
      form.update('firstTime', new Date(2026, 9, 20, 23, 45));

      const saving = form.save();
      const request = http.expectOne('/api/backups/plans/');
      expect(request.request.body).toMatchObject({
        interval_minutes: 1440,
        time_zone: 'Asia/Kolkata',
        anchor_at: '2026-10-20T23:45:00+05:30',
      });
      request.flush(PLAN, { status: 201, statusText: 'Created' });
      await saving;
    });

    it('asks for the missing half, and for a moment after now and within a year', async () => {
      const form = open({ plan: null, name: 'django-dbs' });
      form.update('firstDay', new Date(2026, 9, 20));

      await form.save();
      http.expectNone('/api/backups/plans/');
      expect(form.errorFor('first_time')).toBe('Fill in this field.');

      form.update('firstDay', null);
      form.update('firstTime', new Date(2026, 9, 20, 2, 0));
      expect(form.errorFor('anchor_at')).toBe('Fill in this field.');

      form.update('firstDay', new Date(2026, 8, 20));
      expect(form.error('anchor_at')).toBe('invalid_moment');
      form.update('firstDay', new Date(2027, 11, 20));
      expect(form.errorFor('anchor_at')).toBe('Choose a moment after now and within a year.');
      form.update('firstDay', new Date(2027, 2, 20));
      expect(form.error('anchor_at')).toBeNull();
      expect(form.error('first_time')).toBeNull();
    });

    it('shows a first run and a time zone under the schedule, and neither for a manual plan', () => {
      const form = open({ plan: null, name: 'django-dbs' });

      let view = rendered();
      expect(view.querySelector('fieldset legend')?.textContent).toContain('Backup type');
      expect(Array.from(view.querySelectorAll('legend'), (legend) => legend.textContent?.trim())).toContain('First run');
      expect(view.textContent).toContain('Without it, the first run is one interval after saving.');
      expect(view.textContent).toContain('Daily and weekly plans keep their local time when the clocks change');
      expect(input(view, 'time_zone')?.getAttribute('dir')).toBe('ltr');
      expect(input(view, 'anchor_at_day')).not.toBeNull();
      expect(input(view, 'anchor_at_time')).not.toBeNull();
      expect(view.querySelector('mat-slide-toggle')).not.toBeNull();

      form.setSchedule('manual');
      view = rendered();
      expect(input(view, 'time_zone')).toBeNull();
      expect(input(view, 'anchor_at_day')).toBeNull();
      expect(view.querySelector('mat-slide-toggle')).toBeNull();
    });

    it('sends no first run for a manual plan, even one chosen before', async () => {
      const form = open({ plan: null, name: 'Before upgrade' });
      form.update('firstDay', new Date(2026, 9, 20));
      form.setSchedule('manual');

      const saving = form.save();
      const request = http.expectOne('/api/backups/plans/');
      expect(request.request.body).toMatchObject({ interval_minutes: null, time_zone: BROWSER_ZONE });
      expect(request.request.body).not.toHaveProperty('anchor_at');
      request.flush(MANUAL_PLAN, { status: 201, statusText: 'Created' });
      await saving;
    });

    it("puts the backend's moment refusal under the date until it changes", async () => {
      const form = open({ plan: null, name: 'django-dbs' });
      form.update('firstDay', new Date(2026, 9, 20));
      form.update('firstTime', new Date(2026, 9, 20, 2, 0));

      const saving = form.save();
      http.expectOne('/api/backups/plans/').flush(
        { error: { code: 'invalid', message: 'Server prose', fields: { anchor_at: ['invalid_moment'] } } },
        { status: 400, statusText: 'Bad Request' },
      );
      await saving;

      expect(form.error('anchor_at')).toBe('invalid_moment');
      form.update('firstTime', new Date(2026, 9, 20, 3, 0));
      expect(form.error('anchor_at')).toBeNull();
    });
  });

  describe('the time zone', () => {
    it('offers the zones that match what is typed', async () => {
      const form = open({ plan: null, name: 'django-dbs' });
      rendered();

      const zones = await harnesses.loader(fixture).getHarness(MatAutocompleteHarness);
      await zones.clear();
      await zones.enterText('new york');
      const options = await zones.getOptions();
      expect(await Promise.all(options.map((option) => option.getText()))).toEqual(['America/New_York']);
      await options[0].click();

      expect(form.draft().timeZone).toBe('America/New_York');
    });

    it('holds the save while the zone is not one it knows, and says so under it', async () => {
      const form = open({ plan: null, name: 'django-dbs' });
      form.update('timeZone', 'Mars/Olympus');
      expect(form.zoneOptions()).toEqual([]);

      await form.save();
      http.expectNone('/api/backups/plans/');
      expect(form.errorFor('time_zone')).toBe('Choose a time zone from the list, such as Europe/Berlin.');

      form.update('timeZone', ' ');
      expect(form.error('time_zone')).toBe('required');
      form.update('timeZone', 'UTC');
      expect(form.error('time_zone')).toBeNull();
    });

    it("shows the backend's refusal of the zone under it", async () => {
      const form = open({ plan: null, name: 'django-dbs' });

      const saving = form.save();
      http.expectOne('/api/backups/plans/').flush(
        { error: { code: 'invalid', message: 'Server prose', fields: { time_zone: ['invalid_time_zone'] } } },
        { status: 400, statusText: 'Bad Request' },
      );
      await saving;

      const field = input(rendered(), 'time_zone')?.closest('mat-form-field');
      expect(field?.textContent).toContain('Choose a time zone from the list');
    });
  });

  it("edits a plan from its settings, with its own zone and no first run unless one is chosen", async () => {
    const form = open({ plan: { ...PLAN, time_zone: 'Asia/Riyadh' } });
    expect(form.draft().timeZone).toBe('Asia/Riyadh');
    expect(form.draft().firstDay).toBeNull();
    const view = rendered();
    expect(Array.from(view.querySelectorAll('legend'), (legend) => legend.textContent?.trim())).toContain('Next run');
    expect(view.textContent).toContain("Leave it empty to keep the plan's times.");
    form.update('enabled', false);

    const saving = form.save();
    const request = http.expectOne(`/api/backups/plans/${PLAN.id}/`);
    expect(request.request.method).toBe('PATCH');
    expect(request.request.body).toEqual({
      name: PLAN.name,
      interval_minutes: 1440,
      keep: PLAN.keep,
      keep_remote: PLAN.keep_remote,
      enabled: false,
      paths: [],
      pattern: '',
      time_zone: 'Asia/Riyadh',
    });
    request.flush({ ...PLAN, enabled: false });
    await saving;

    expect(close).toHaveBeenCalledWith({ ...PLAN, enabled: false });
  });

  it('edits a manual plan, sending no interval', async () => {
    const form = open({ plan: MANUAL_PLAN });
    expect(form.draft().schedule).toBe('manual');

    const saving = form.save();
    const request = http.expectOne(`/api/backups/plans/${MANUAL_PLAN.id}/`);
    expect(request.request.body).toMatchObject({ interval_minutes: null, time_zone: 'UTC' });
    request.flush(MANUAL_PLAN);
    await saving;
  });

  it("puts the backend's field errors under their fields, and drops one once its field is edited", async () => {
    const form = open({ plan: PLAN });

    const saving = form.save();
    http.expectOne(`/api/backups/plans/${PLAN.id}/`).flush(
      {
        error: {
          code: 'invalid',
          message: 'Server prose',
          fields: { name: ['name_taken'], interval_minutes: ['invalid_interval'] },
        },
      },
      { status: 400, statusText: 'Bad Request' },
    );
    await saving;

    expect(close).not.toHaveBeenCalled();
    expect(form.error('name')).toBe('name_taken');
    expect(form.error('interval_minutes')).toBe('invalid_interval');

    form.setSchedule('weekly');
    expect(form.error('interval_minutes')).toBeNull();
    expect(form.error('name')).toBe('name_taken');
  });

  describe('what the plan backs up', () => {
    it('offers the three kinds on a new plan, and the folder list only for folders', async () => {
      const form = open({ plan: null });

      let view = rendered();
      expect(await radioLabels()).toEqual(['django-dbs', 'Folders', 'Existing files']);
      expect(await chipGrids()).toBe(0);
      expect(view.textContent).toContain("The application's backup passphrase encrypts each backup.");

      form.setKind('archive');
      view = rendered();
      expect(await chipGrids()).toBe(1);
      expect(view.textContent).toContain('kept here encrypted');
      expect(view.textContent).toContain('django-dbs backups already include the files their models point at.');
    });

    it('opens on folders when the opener asks for them', () => {
      const form = open({ plan: null, kind: 'archive' });

      expect(form.draft().kind).toBe('archive');
      expect(form.draft().name).toBe('');
      expect(form.archiving()).toBe(true);
    });

    it('holds the save of a folder plan until it has a folder, each a full path with no .. step', async () => {
      const form = open({ plan: null, name: 'Media', kind: 'archive' });

      await form.save();
      http.expectNone('/api/backups/plans/');
      expect(form.error('paths')).toBe('paths_required');

      form.update('paths', ['/srv/app/media', 'srv/app/uploads']);
      expect(form.error('paths')).toBe('absolute_path_required');

      form.update('paths', ['/srv/app/../../etc']);
      expect(form.error('paths')).toBe('absolute_path_required');

      form.update('paths', ['/srv/app/media..old']);
      expect(form.error('paths')).toBeNull();
    });

    it('sends the kind and the folders of a folder plan, with the password', async () => {
      const form = open({ plan: null, kind: 'archive' });
      form.update('name', 'Media');
      form.update('paths', ['/srv/app/media', '/srv/app/uploads']);
      form.setSchedule('weekly');
      form.setAccountPassword(PASSWORD);

      const saving = form.save();
      const request = http.expectOne('/api/backups/plans/');
      expect(request.request.body).toEqual({
        application: APPLICATION_ID,
        kind: 'archive',
        name: 'Media',
        interval_minutes: 10080,
        keep: 5,
        keep_remote: 0,
        enabled: true,
        paths: ['/srv/app/media', '/srv/app/uploads'],
        pattern: '',
        time_zone: BROWSER_ZONE,
        account_password: PASSWORD,
      });
      request.flush(ARCHIVE_PLAN, { status: 201, statusText: 'Created' });
      await saving;

      expect(close).toHaveBeenCalledWith(ARCHIVE_PLAN);
    });

    it('drops the folders when the kind goes back to django-dbs', async () => {
      const form = open({ plan: null, name: 'django-dbs', kind: 'archive' });
      form.update('paths', ['relative/path']);
      form.setKind('dbs');

      const saving = form.save();
      const request = http.expectOne('/api/backups/plans/');
      expect(request.request.body).toMatchObject({ kind: 'dbs', paths: [] });
      request.flush(PLAN, { status: 201, statusText: 'Created' });
      await saving;
    });

    it("shows an existing plan's kind as a fact, and edits its folders without sending the kind", async () => {
      const form = open({ plan: ARCHIVE_PLAN });

      const view = rendered();
      expect(await radioLabels()).toEqual([]);
      expect(view.querySelector('dl')?.textContent).toContain('Backup type');
      expect(view.querySelector('dl')?.textContent).toContain('Folders');
      expect(await chipGrids()).toBe(1);

      form.update('paths', ['/srv/app/media']);
      form.setAccountPassword(PASSWORD);
      const saving = form.save();
      const request = http.expectOne(`/api/backups/plans/${ARCHIVE_PLAN.id}/`);
      expect(request.request.body).not.toHaveProperty('kind');
      expect(request.request.body).toMatchObject({ paths: ['/srv/app/media'], account_password: PASSWORD });
      request.flush({ ...ARCHIVE_PLAN, paths: ['/srv/app/media'] });
      await saving;
    });

    it("says under the kind what the backend found wrong with a django-dbs plan's folders", async () => {
      const form = open({ plan: null, name: 'django-dbs' });

      const saving = form.save();
      http.expectOne('/api/backups/plans/').flush(
        { error: { code: 'invalid', message: 'Server prose', fields: { paths: ['paths_not_allowed'] } } },
        { status: 400, statusText: 'Bad Request' },
      );
      await saving;

      expect(form.kindError()).toBe('paths_not_allowed');
      expect(rendered().querySelector('fieldset')?.textContent).toContain('A django-dbs plan takes no folders.');

      form.setKind('archive');
      expect(form.kindError()).toBeNull();
      expect(form.error('paths')).toBe('paths_required');
    });
  });

  describe('collecting existing files', () => {
    it('asks for one folder and a pattern, both read left to right, and not for copies on the server', async () => {
      const form = open({ plan: null, kind: 'collect' });

      const view = rendered();
      expect(form.collecting()).toBe(true);
      expect(form.draft().pattern).toBe('*');
      expect(await chipGrids()).toBe(0);
      expect(input(view, 'folder')?.getAttribute('dir')).toBe('ltr');
      expect(input(view, 'pattern')?.getAttribute('dir')).toBe('ltr');
      expect(input(view, 'pattern')?.getAttribute('maxlength')).toBe('200');
      expect(input(view, 'keep_remote')).toBeNull();
      expect(input(view, 'keep')).not.toBeNull();
      expect(view.textContent).toContain('*.sql.gz matches every .sql.gz file in the folder.');
    });

    it('holds the save until the folder is a full path and the pattern has no /', async () => {
      const form = open({ plan: null, name: 'Database dumps', kind: 'collect' });
      form.update('pattern', ' ');

      await form.save();
      http.expectNone('/api/backups/plans/');
      expect(form.error('paths')).toBe('required');
      expect(form.error('pattern')).toBe('required');

      form.update('folder', 'var/backups');
      form.update('pattern', 'postgres/*.sql.gz');
      expect(form.error('paths')).toBe('absolute_path_required');
      expect(form.error('pattern')).toBe('invalid_pattern');

      form.update('folder', '/var/backups/postgres');
      form.update('pattern', '*.sql.gz');
      expect(form.error('paths')).toBeNull();
      expect(form.error('pattern')).toBeNull();
    });

    it('sends its one folder and its pattern, and keeps nothing on the server', async () => {
      const form = open({ plan: null, kind: 'collect' });
      form.update('name', 'Database dumps');
      form.update('folder', ' /var/backups/postgres ');
      form.update('pattern', '*.sql.gz ');
      form.update('keep', 4);
      form.update('keep_remote', 2);
      form.setAccountPassword(PASSWORD);

      const saving = form.save();
      const request = http.expectOne('/api/backups/plans/');
      expect(request.request.body).toMatchObject({
        kind: 'collect',
        keep: 4,
        keep_remote: 0,
        paths: ['/var/backups/postgres'],
        pattern: '*.sql.gz',
      });
      request.flush(COLLECT_PLAN, { status: 201, statusText: 'Created' });
      await saving;

      expect(close).toHaveBeenCalledWith(COLLECT_PLAN);
    });

    it("puts the backend's codes under the folder and the pattern", async () => {
      const form = open({ plan: null, name: 'Database dumps', kind: 'collect' });
      form.update('folder', '/var/backups/postgres');
      form.setAccountPassword(PASSWORD);

      const saving = form.save();
      http.expectOne('/api/backups/plans/').flush(
        {
          error: {
            code: 'invalid',
            message: 'Server prose',
            fields: { paths: ['one_folder_required'], pattern: ['invalid_pattern'] },
          },
        },
        { status: 400, statusText: 'Bad Request' },
      );
      await saving;

      const view = rendered();
      expect(input(view, 'folder')?.closest('mat-form-field')?.textContent).toContain('Enter one folder.');
      expect(input(view, 'pattern')?.closest('mat-form-field')?.textContent).toContain('Use a pattern with no / in it.');
    });
  });

  describe("the reader's password", () => {
    it('is asked for before a plan that reads the server is added, and never for a django-dbs plan', async () => {
      const form = open({ plan: null, name: 'Media', kind: 'archive' });
      form.update('paths', ['/srv/app/media']);
      expect(form.passwordShown()).toBe(true);

      await form.save();

      expect(form.passwordMissing()).toBe(true);
      const field = rendered().querySelector('input[name="account_password"]')?.closest('mat-form-field');
      expect(field?.querySelector('mat-error')).not.toBeNull();

      form.setKind('dbs');
      expect(form.passwordShown()).toBe(false);
    });

    it("is not asked for when a plan's folders stay as they are and it keeps as many", async () => {
      const form = open({ plan: ARCHIVE_PLAN });
      form.update('keep', 5);
      form.update('keep_remote', 2);
      expect(form.passwordShown()).toBe(false);

      const saving = form.save();
      const request = http.expectOne(`/api/backups/plans/${ARCHIVE_PLAN.id}/`);
      expect(request.request.body).not.toHaveProperty('account_password');
      request.flush({ ...ARCHIVE_PLAN, keep: 5, keep_remote: 2 });
      await saving;

      form.update('paths', [...ARCHIVE_PLAN.paths, '/srv/app/static']);
      expect(form.passwordShown()).toBe(true);
    });

    it('is asked for before a plan keeps fewer here or on the server, which deletes the oldest', async () => {
      const form = open({ plan: PLAN });

      form.update('keep', PLAN.keep - 1);
      expect(form.passwordShown()).toBe(true);
      expect(rendered().textContent).toContain('Keeping fewer backups deletes the oldest ones on the next run');

      form.update('keep', PLAN.keep);
      expect(form.passwordShown()).toBe(false);
      form.update('keep_remote', PLAN.keep_remote - 1);
      expect(form.passwordShown()).toBe(true);

      await form.save();
      http.expectNone(`/api/backups/plans/${PLAN.id}/`);
      expect(form.passwordMissing()).toBe(true);

      form.setAccountPassword(PASSWORD);
      const saving = form.save();
      const request = http.expectOne(`/api/backups/plans/${PLAN.id}/`);
      expect(request.request.body).toMatchObject({ keep: PLAN.keep, keep_remote: 0, account_password: PASSWORD });
      request.flush({ ...PLAN, keep_remote: 0 });
      await saving;
      expect(close).toHaveBeenCalledWith({ ...PLAN, keep_remote: 0 });
    });

    it('asks for its password when the backend says a change needs it', async () => {
      const form = open({ plan: MANUAL_PLAN });

      const saving = form.save();
      http.expectOne(`/api/backups/plans/${MANUAL_PLAN.id}/`).flush(
        { error: { code: 'invalid', message: 'Server prose', fields: { account_password: ['required'] } } },
        { status: 400, statusText: 'Bad Request' },
      );
      await saving;

      expect(form.passwordShown()).toBe(true);
      expect(form.passwordMissing()).toBe(true);
    });

    it('says a wrong password under its field, and stops once it is typed again', async () => {
      const form = open({ plan: null, name: 'Media', kind: 'archive' });
      form.update('paths', ['/srv/app/media']);
      form.setAccountPassword('wrong');

      const saving = form.save();
      http.expectOne('/api/backups/plans/').flush(
        { error: { code: 'invalid_password', message: 'Server prose' } },
        { status: 400, statusText: 'Bad Request' },
      );
      await saving;

      expect(close).not.toHaveBeenCalled();
      expect(form.passwordRejected()).toBe(true);
      expect(form.formFailure()).toBeNull();

      form.setAccountPassword(PASSWORD);
      expect(form.passwordRejected()).toBe(false);
    });
  });
});
