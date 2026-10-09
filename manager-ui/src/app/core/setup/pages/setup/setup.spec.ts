import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { SetupPage } from './setup';

describe('SetupPage', () => {
  let http: HttpTestingController;
  let fixture: ComponentFixture<SetupPage>;
  let page: SetupPage;

  const rendered = (): HTMLElement => {
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  };

  const errors = (): string[] =>
    Array.from(rendered().querySelectorAll('.field__error')).map((node) => node.textContent?.trim() ?? '');

  const fill = (): void => {
    page.username.set(' sara ');
    page.password.set('a long passphrase');
    page.confirm.set('a long passphrase');
  };

  const post = async (): Promise<void> => {
    http.expectOne('/api/auth/csrf/').flush(null);
    await vi.waitFor(() => http.expectOne('/api/setup/')).then((request) => {
      expect(request.request.body).toEqual({ token: 'k3y', username: 'sara', password: 'a long passphrase' });
      request.flush({ username: 'sara' }, { status: 201, statusText: 'Created' });
    });
  };

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    TestBed.inject(LocaleStore).register({ en, ar });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(SetupPage);
    page = fixture.componentInstance;
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('asks for the setup key only when the link did not carry it', () => {
    expect(rendered().querySelector('input[name="token"]')).not.toBeNull();

    fixture.componentRef.setInput('token', 'k3y');
    expect(rendered().querySelector('input[name="token"]')).toBeNull();
  });

  it('holds the request until every field is filled and both passwords match', async () => {
    await page.submit();
    expect(errors()).toEqual(['Enter the setup key.', 'Enter a username.', 'Enter a password.']);

    fixture.componentRef.setInput('token', 'k3y');
    fill();
    page.confirm.set('something else');
    await page.submit();
    expect(errors()).toEqual(['The passwords do not match.']);
    http.expectNone('/api/setup/');
  });

  it('creates the account, loads who is signed in and opens the start page', async () => {
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    fixture.componentRef.setInput('token', 'k3y');
    fill();

    const submitting = page.submit();
    await post();
    (await vi.waitFor(() => http.expectOne('/api/auth/me/'))).flush({
      id: 1,
      username: 'sara',
      email: '',
      first_name: '',
      last_name: '',
      is_staff: true,
      is_superuser: true,
      groups: [],
      permissions: [],
    });
    await submitting;

    expect(navigate).toHaveBeenCalledWith('/');
  });

  it('shows what the backend says about the password under its field', async () => {
    fixture.componentRef.setInput('token', 'k3y');
    fill();

    const submitting = page.submit();
    http.expectOne('/api/auth/csrf/').flush(null);
    (await vi.waitFor(() => http.expectOne('/api/setup/'))).flush(
      { error: { code: 'invalid', message: 'Server prose', fields: { password: ['password_too_common'] } } },
      { status: 400, statusText: 'Bad Request' },
    );
    await submitting;

    expect(errors()).toEqual(['The password is too common.']);
  });

  it('offers sign-in once an account already exists', async () => {
    fixture.componentRef.setInput('token', 'k3y');
    fill();

    const submitting = page.submit();
    http.expectOne('/api/auth/csrf/').flush(null);
    (await vi.waitFor(() => http.expectOne('/api/setup/'))).flush(
      { error: { code: 'setup_done', message: 'Server prose' } },
      { status: 409, statusText: 'Conflict' },
    );
    await submitting;

    const html = rendered();
    expect(html.textContent).toContain('An account already exists. Sign in with it.');
    expect(html.querySelector('a[href="/sign-in"]')?.textContent?.trim()).toBe('Go to sign in');
    expect(html.querySelector('form')).toBeNull();
  });
});
