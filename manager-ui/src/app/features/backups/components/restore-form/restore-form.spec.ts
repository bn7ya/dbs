import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { NEVER } from 'rxjs';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import { Toaster } from '@shared/toaster/toaster';
import { JobWatcher } from '@core/jobs/job-watcher';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { BackupsStore } from '../../state/backups.store';
import { FILE, JOB_ID, SERVER_ID } from '../../testing/backups.fixtures';
import { RestoreForm } from './restore-form';

const PASSWORD = 'correct-horse-battery-staple';

describe('RestoreForm', () => {
  let http: HttpTestingController;
  let close: ReturnType<typeof vi.fn>;
  let fixture: ComponentFixture<RestoreForm>;

  const open = (): RestoreForm => {
    close = vi.fn();
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [
        BackupsStore,
        // The form's spec is not about following the job; the store's is.
        { provide: JobWatcher, useValue: { watch: () => NEVER } },
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: MatDialogRef, useValue: { close } },
        { provide: MAT_DIALOG_DATA, useValue: { data: { file: FILE } } },
      ],
    });
    TestBed.inject(LocaleStore).register({ en, ar });
    TestBed.inject(BackupsStore).server.set(SERVER_ID);
    vi.spyOn(TestBed.inject(Toaster), 'add').mockReturnValue(undefined);
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(RestoreForm);
    return fixture.componentInstance;
  };

  const rendered = (): HTMLElement => {
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  };

  const restoreRequest = () => http.expectOne(`/api/backups/${FILE.id}/restore/`);

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('names the file and the server, and starts on merge', () => {
    const form = open();
    const text = rendered().textContent ?? '';

    expect(text).toContain(FILE.name);
    expect(text).toContain(FILE.server_name);
    expect(text).toContain('Records added since this backup stay.');
    expect(form.mode()).toBe('merge');

    form.setMode('replace');
    expect(rendered().textContent).toContain('The backed-up tables are cleared first.');
  });

  it('rehearses with neither the password nor the name, then closes', async () => {
    const form = open();
    form.setMode('replace');

    const rehearsing = form.rehearse();
    expect(form.sending()).toBe('rehearse');
    const request = restoreRequest();
    expect(request.request.body).toEqual({ mode: 'replace', rehearse: true });
    request.flush({ activity: JOB_ID }, { status: 202, statusText: 'Accepted' });
    await rehearsing;

    expect(form.sending()).toBeNull();
    expect(close).toHaveBeenCalledWith(true);
  });

  it('holds a restore for real until the password is there and the name matches, and says why', async () => {
    const form = open();

    await form.restore();

    http.expectNone(`/api/backups/${FILE.id}/restore/`);
    expect(form.passwordMissing()).toBe(true);
    expect(form.nameError()).toBe('name_mismatch');
    const fields = rendered().querySelectorAll('mat-error');
    expect(Array.from(fields, (each) => each.textContent?.trim())).toEqual([
      'Enter your password.',
      "Type the server's name exactly as shown.",
    ]);

    form.setServerName(FILE.server_name.toUpperCase());
    await form.restore();
    http.expectNone(`/api/backups/${FILE.id}/restore/`);
    expect(form.nameError()).toBe('name_mismatch');
  });

  it('restores for real with the password and the name, spaces around it aside', async () => {
    const form = open();
    form.setAccountPassword(PASSWORD);
    form.setServerName(`  ${FILE.server_name} `);

    const restoring = form.restore();
    const request = restoreRequest();
    expect(request.request.body).toEqual({
      mode: 'merge',
      rehearse: false,
      account_password: PASSWORD,
      server_name: FILE.server_name,
    });
    request.flush({ activity: JOB_ID }, { status: 202, statusText: 'Accepted' });
    await restoring;

    expect(close).toHaveBeenCalledWith(true);
  });

  it('says a wrong password under its field, and stops once it is typed again', async () => {
    const form = open();
    form.setAccountPassword('wrong');
    form.setServerName(FILE.server_name);

    const restoring = form.restore();
    restoreRequest().flush(
      { error: { code: 'invalid_password', message: 'Server prose' } },
      { status: 400, statusText: 'Bad Request' },
    );
    await restoring;

    expect(close).not.toHaveBeenCalled();
    expect(form.passwordRejected()).toBe(true);
    expect(form.formFailure()).toBeNull();
    expect(rendered().textContent).toContain('The password is not correct.');

    form.setAccountPassword(PASSWORD);
    expect(form.passwordRejected()).toBe(false);
  });

  it('says above the form what is not about a field', async () => {
    const form = open();

    const rehearsing = form.rehearse();
    restoreRequest().flush(
      { error: { code: 'backup_running', message: 'Server prose' } },
      { status: 409, statusText: 'Conflict' },
    );
    await rehearsing;

    expect(form.formFailure()?.code).toBe('backup_running');
    expect(rendered().querySelector('app-notice')?.textContent).toContain(
      'A backup or restore of this server is already running.',
    );
  });
});
