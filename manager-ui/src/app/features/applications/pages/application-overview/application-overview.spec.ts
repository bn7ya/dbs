import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import type { Type } from '@angular/core';
import { ApplicationRef } from '@angular/core';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';

import { AuthStore } from '@core/auth/state/auth.store';
import { OPERATOR } from '@core/auth/testing/identity.fixtures';
import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import { Dialogs } from '@shared/dialogs/dialogs';
import type { DialogOptions } from '@shared/dialogs/dialogs.types';
import type { PasswordPromptData } from '@shared/password-prompt/password-prompt.types';
import { Toaster } from '@shared/toaster/toaster';
import type { Application } from '../../data/applications.types';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { ApplicationsStore } from '../../state/applications.store';
import { APPLICATION, CHECKED, SERVER_ID } from '../../testing/applications.fixtures';
import { ApplicationOverviewPage } from './application-overview';

const DETAIL = `/api/applications/${APPLICATION.id}/`;

describe('ApplicationOverviewPage', () => {
  let http: HttpTestingController;
  let fixture: ComponentFixture<ApplicationOverviewPage>;
  let typed: string[];
  let prompted: Mock<(component: Type<unknown>, options: DialogOptions<PasswordPromptData>) => Promise<true | undefined>>;

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const html = (): HTMLElement => {
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  };

  const show = async (application: Application = APPLICATION): Promise<ApplicationOverviewPage> => {
    const store = TestBed.inject(ApplicationsStore);
    fixture = TestBed.createComponent(ApplicationOverviewPage);
    store.select(application.id);
    TestBed.tick();
    http.expectOne(`/api/applications/${application.id}/`).flush(application);
    await settle();
    html();
    return fixture.componentInstance;
  };

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    typed = [];
    prompted = vi.fn(async (_component: Type<unknown>, options: DialogOptions<PasswordPromptData>) => {
      for (const password of typed) {
        if (await options.data?.submit(password)) {
          return true;
        }
      }
      return undefined;
    });
    TestBed.overrideComponent(ApplicationOverviewPage, {
      set: {
        providers: [
          {
            provide: Dialogs,
            useValue: {
              open: (component: Type<unknown>, options: DialogOptions<PasswordPromptData>) => ({
                whenClosed: () => prompted(component, options),
              }),
            },
          },
        ],
      },
    });
    TestBed.configureTestingModule({
      providers: [
        ApplicationsStore,
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    TestBed.inject(LocaleStore).register({ en, ar });
    vi.spyOn(TestBed.inject(Toaster), 'add').mockReturnValue(undefined);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('shows the settings, where the .env file is and the mounted folders', async () => {
    await show();

    const page = html().textContent ?? '';
    expect(page).toContain('In a Compose service');
    expect(page).toContain('/srv/shop/.env');
    expect(page).toContain('/srv/shop/media');
    expect(page).toContain('read only');
    expect(page).not.toContain('is lost when the container is created again');
  });

  it('warns that a .env file inside the container is lost when it is created again', async () => {
    await show({ ...APPLICATION, env_path: '/app/.env', env_location: 'container' });

    expect(html().textContent).toContain('is lost when the container is created again');
  });

  it('runs the check and shows its report with both django-dbs versions', async () => {
    const page = await show();

    const checking = page.check();
    http.expectOne(`${DETAIL}check/`).flush(CHECKED);
    await checking;

    const text = html().textContent ?? '';
    expect(text).toContain('django-dbs here and in the application work together.');
    expect(text).toContain('27.3.1');
    expect(text).toContain('Running');
  });

  it('switches the Python behind the password when the backend asks for it', async () => {
    const page = await show({
      ...APPLICATION,
      last_check_status: 'problem',
      last_check_report: {
        ...APPLICATION.last_check_report,
        dbs_version: null,
        python_suggestion: { python_path: '/app/venv/bin/python', dbs_version: '0.8.0' },
      },
    });
    expect(html().textContent).toContain('django-dbs 0.8.0 was found in');

    typed = ['hunter2'];
    const switching = page.useSuggestedPython();
    http.expectOne(DETAIL).flush(
      { error: { code: 'invalid', message: 'prose', fields: { account_password: ['required'] } } },
      { status: 400, statusText: 'Bad Request' },
    );
    const retried = await vi.waitFor(() => http.expectOne(DETAIL));
    expect(retried.request.body).toEqual({ python_path: '/app/venv/bin/python', account_password: 'hunter2' });
    retried.flush({ ...APPLICATION, python_path: '/app/venv/bin/python' });
    (await vi.waitFor(() => http.expectOne(`${DETAIL}check/`))).flush(CHECKED);
    await switching;

    expect(prompted).toHaveBeenCalledOnce();
  });

  it('reveals the backup passphrase behind the password, with the warning that it never changes', async () => {
    const page = await show();
    expect(html().textContent).toContain('Never change this passphrase');

    typed = ['hunter2'];
    const revealing = page.togglePassphrase();
    (await vi.waitFor(() => http.expectOne(`${DETAIL}passphrase/`))).flush({ passphrase: 'correct horse battery staple' });
    await revealing;

    expect(html().querySelector<HTMLInputElement>('input[readonly]')?.value).toBe('correct horse battery staple');
    await page.togglePassphrase();
    expect(html().querySelector('input[readonly]')).toBeNull();
  });

  it('offers to read the passphrase while the application has none', async () => {
    const page = await show({ ...APPLICATION, has_backup_passphrase: false });
    expect(html().textContent).toContain('before its first backup');

    const capturing = page.capturePassphrase();
    http.expectOne(`${DETAIL}passphrase/capture/`).flush({ captured: true });
    await capturing;
    TestBed.tick();
    http.expectOne(DETAIL).flush(APPLICATION);
    await settle();

    expect(html().textContent).toContain('Never change this passphrase');
  });

  it('hides editing, the passphrase and removing from an operator, but keeps the check', async () => {
    const restoring = TestBed.inject(AuthStore).restore();
    http.expectOne('/api/auth/me/').flush(OPERATOR);
    await restoring;
    await show();

    const labels = Array.from(html().querySelectorAll('button'), (button) => button.textContent?.trim());
    expect(labels).toContain('Check now');
    expect(labels).not.toContain('Edit');
    expect(labels).not.toContain('Show passphrase');
    expect(labels).not.toContain('Remove application');
  });

  it('removes the application behind the password and goes back to its server', async () => {
    const page = await show();
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);

    typed = ['hunter2'];
    const removing = page.remove();
    const request = await vi.waitFor(() => http.expectOne(DETAIL));
    expect(request.request.method).toBe('DELETE');
    request.flush(null, { status: 204, statusText: 'No Content' });
    await removing;

    expect(prompted.mock.calls[0][1].data).toMatchObject({ destructive: true, bodyValues: { name: '⁨shop⁩' } });
    expect(navigate).toHaveBeenCalledWith(['/servers', SERVER_ID, 'applications']);
  });
});
