import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { MatChipGridHarness } from '@angular/material/chips/testing';
import { MatRadioButtonHarness } from '@angular/material/radio/testing';
import { provideRouter } from '@angular/router';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import { Toaster } from '@shared/toaster/toaster';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { BackupsStore } from '../../state/backups.store';
import { ARCHIVE_PLAN, COLLECT_PLAN, MANUAL_PLAN, PLAN, SERVER_ID } from '../../testing/backups.fixtures';
import { PlanForm } from './plan-form';
import type { PlanFormData } from './plan-form.types';

const PASSWORD = 'correct-horse-battery-staple';

describe('PlanForm', () => {
  let http: HttpTestingController;
  let close: ReturnType<typeof vi.fn>;
  let fixture: ComponentFixture<PlanForm>;

  const open = (data: PlanFormData): PlanForm => {
    close = vi.fn();
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [
        BackupsStore,
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: MatDialogRef, useValue: { close } },
        { provide: MAT_DIALOG_DATA, useValue: { data } },
      ],
    });
    TestBed.inject(LocaleStore).register({ en, ar });
    TestBed.inject(BackupsStore).server.set(SERVER_ID);
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

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('starts a new plan daily, keeping seven here and one on the server, enabled, with the name given', () => {
    const form = open({ plan: null, name: 'django-dbs' });

    expect(form.draft()).toEqual({
      kind: 'dbs',
      paths: [],
      folder: '',
      pattern: '*',
      name: 'django-dbs',
      schedule: 'daily',
      keep: 7,
      keep_remote: 1,
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
    form.update('keep_remote', 400);

    await form.save();

    http.expectNone('/api/backups/plans/');
    expect(form.error('name')).toBe('required');
    expect(form.error('keep')).toBe('required');
    expect(form.error('keep_remote')).toBe('keep_remote_range');

    form.update('keep', 0);
    expect(form.error('keep')).toBe('keep_range');
  });

  it('sends the interval of the schedule chosen, then closes with the plan', async () => {
    const form = open({ plan: null, name: 'django-dbs' });
    form.setSchedule('every6Hours');
    form.update('keep_remote', 0);

    const saving = form.save();
    const request = http.expectOne('/api/backups/plans/');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({
      server: SERVER_ID,
      kind: 'dbs',
      name: 'django-dbs',
      interval_minutes: 360,
      keep: 7,
      keep_remote: 0,
      enabled: true,
      paths: [],
      pattern: '',
    });
    request.flush({ ...PLAN, interval_minutes: 360, keep_remote: 0 }, { status: 201, statusText: 'Created' });
    await saving;

    expect(close).toHaveBeenCalledWith({ ...PLAN, interval_minutes: 360, keep_remote: 0 });
  });

  it('edits a plan from its settings, a manual one sending no interval', async () => {
    const form = open({ plan: MANUAL_PLAN });
    expect(form.draft().schedule).toBe('manual');
    form.update('enabled', false);

    const saving = form.save();
    const request = http.expectOne(`/api/backups/plans/${MANUAL_PLAN.id}/`);
    expect(request.request.method).toBe('PATCH');
    expect(request.request.body).toEqual({
      name: MANUAL_PLAN.name,
      interval_minutes: null,
      keep: MANUAL_PLAN.keep,
      keep_remote: MANUAL_PLAN.keep_remote,
      enabled: false,
      paths: [],
      pattern: '',
    });
    request.flush({ ...MANUAL_PLAN, enabled: false });
    await saving;

    expect(close).toHaveBeenCalledWith({ ...MANUAL_PLAN, enabled: false });
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
      expect(view.textContent).toContain("The server's backup passphrase encrypts each backup.");

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

    it('sends the kind and the folders of a folder plan', async () => {
      const form = open({ plan: null, kind: 'archive' });
      form.update('name', 'Media');
      form.update('paths', ['/srv/app/media', '/srv/app/uploads']);
      form.setSchedule('weekly');
      form.setAccountPassword(PASSWORD);

      const saving = form.save();
      const request = http.expectOne('/api/backups/plans/');
      expect(request.request.body).toEqual({
        server: SERVER_ID,
        kind: 'archive',
        name: 'Media',
        interval_minutes: 10080,
        keep: 7,
        keep_remote: 1,
        enabled: true,
        paths: ['/srv/app/media', '/srv/app/uploads'],
        pattern: '',
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
      expect(request.request.method).toBe('PATCH');
      expect(request.request.body).toEqual({
        name: ARCHIVE_PLAN.name,
        interval_minutes: 10080,
        keep: ARCHIVE_PLAN.keep,
        keep_remote: ARCHIVE_PLAN.keep_remote,
        enabled: true,
        paths: ['/srv/app/media'],
        pattern: '',
        account_password: PASSWORD,
      });
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
      expect(rendered().querySelector('fieldset')?.textContent).toContain(
        'A django-dbs plan takes no folders.',
      );

      form.setKind('archive');
      expect(form.kindError()).toBeNull();
      expect(form.error('paths')).toBe('paths_required');
    });
  });

  describe('collecting existing files', () => {
    const input = (view: HTMLElement, name: string): HTMLInputElement | null =>
      view.querySelector<HTMLInputElement>(`input[name="${name}"]`);

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
      expect(view.textContent).toContain("the server's copy stays as it is.");
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

      form.update('folder', '/var/backups/../etc');
      expect(form.error('paths')).toBe('absolute_path_required');

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
      form.update('keep', 14);
      form.setAccountPassword(PASSWORD);
      expect(form.draft().keep_remote).toBe(1);

      const saving = form.save();
      const request = http.expectOne('/api/backups/plans/');
      expect(request.request.body).toEqual({
        server: SERVER_ID,
        kind: 'collect',
        name: 'Database dumps',
        interval_minutes: 1440,
        keep: 14,
        keep_remote: 0,
        enabled: true,
        paths: ['/var/backups/postgres'],
        pattern: '*.sql.gz',
        account_password: PASSWORD,
      });
      request.flush(COLLECT_PLAN, { status: 201, statusText: 'Created' });
      await saving;

      expect(close).toHaveBeenCalledWith(COLLECT_PLAN);
    });

    it('keeps what was typed for each kind when the kind changes, and sends only the one chosen', async () => {
      const form = open({ plan: null, name: 'Media', kind: 'archive' });
      form.update('paths', ['/srv/app/media']);
      form.setKind('collect');
      form.update('folder', '/var/backups');
      form.setKind('archive');

      expect(form.draft().paths).toEqual(['/srv/app/media']);
      expect(form.draft().folder).toBe('/var/backups');

      form.setAccountPassword(PASSWORD);
      const saving = form.save();
      const request = http.expectOne('/api/backups/plans/');
      expect(request.request.body).toMatchObject({ kind: 'archive', paths: ['/srv/app/media'], pattern: '', keep_remote: 1 });
      request.flush(ARCHIVE_PLAN, { status: 201, statusText: 'Created' });
      await saving;
    });

    it("edits a collection from its folder and pattern, showing its kind as a fact", async () => {
      const form = open({ plan: COLLECT_PLAN });

      const view = rendered();
      await fixture.whenStable();
      expect(await radioLabels()).toEqual([]);
      expect(view.querySelector('dl')?.textContent).toContain('Existing files');
      expect(input(view, 'folder')?.value).toBe('/var/backups/postgres');
      expect(input(view, 'pattern')?.value).toBe('*.sql.gz');
      expect(input(view, 'keep_remote')).toBeNull();

      form.update('pattern', '*.dump');
      form.setAccountPassword(PASSWORD);
      const saving = form.save();
      const request = http.expectOne(`/api/backups/plans/${COLLECT_PLAN.id}/`);
      expect(request.request.method).toBe('PATCH');
      expect(request.request.body).toEqual({
        name: COLLECT_PLAN.name,
        interval_minutes: 1440,
        keep: 14,
        keep_remote: 0,
        enabled: true,
        paths: ['/var/backups/postgres'],
        pattern: '*.dump',
        account_password: PASSWORD,
      });
      request.flush({ ...COLLECT_PLAN, pattern: '*.dump' });
      await saving;
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
            fields: {
              paths: ['one_folder_required'],
              pattern: ['invalid_pattern'],
            },
          },
        },
        { status: 400, statusText: 'Bad Request' },
      );
      await saving;

      const view = rendered();
      expect(form.error('paths')).toBe('one_folder_required');
      expect(form.error('pattern')).toBe('invalid_pattern');
      expect(form.kindError()).toBeNull();
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

    it("is not asked for when a plan's folders stay as they are", async () => {
      const form = open({ plan: ARCHIVE_PLAN });
      form.update('keep', 3);
      expect(form.passwordShown()).toBe(false);

      const saving = form.save();
      const request = http.expectOne(`/api/backups/plans/${ARCHIVE_PLAN.id}/`);
      expect(request.request.body).not.toHaveProperty('account_password');
      request.flush({ ...ARCHIVE_PLAN, keep: 3 });
      await saving;

      form.update('paths', [...ARCHIVE_PLAN.paths, '/srv/app/static']);
      expect(form.passwordShown()).toBe(true);
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
