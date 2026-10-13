import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { AuthStore } from '../../state/auth.store';
import { MASTER } from '../../testing/identity.fixtures';
import { ChangePasswordForm } from './change-password-form';

describe('ChangePasswordForm', () => {
  let http: HttpTestingController;
  let fixture: ComponentFixture<ChangePasswordForm>;
  let form: ChangePasswordForm;

  const errors = async (): Promise<string[]> => {
    await TestBed.inject(ApplicationRef).whenStable();
    fixture.detectChanges();
    return Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('mat-error')).map(
      (node) => node.textContent?.trim() ?? '',
    );
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
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(ChangePasswordForm);
    form = fixture.componentInstance;
    fixture.detectChanges();
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it('asks for every field and a matching confirmation before sending', async () => {
    await form.submit();
    expect(await errors()).toEqual(['Enter your password.', 'Enter a new password.']);

    form.current.set('old one');
    form.fresh.set('a new long passphrase');
    form.confirm.set('something else');
    await form.submit();
    expect(await errors()).toEqual(['The two new passwords do not match.']);
    http.expectNone('/api/auth/password/');
  });

  it('shows what the backend says about each password', async () => {
    form.current.set('old one');
    form.fresh.set('old one');
    form.confirm.set('old one');

    const submitting = form.submit();
    http.expectOne('/api/auth/password/').flush(
      { error: { code: 'invalid', message: 'No', fields: { new_password: ['password_unchanged'] } } },
      { status: 400, statusText: 'Bad Request' },
    );
    await submitting;

    expect(await errors()).toEqual(['Choose a password you have not been using.']);
  });

  it('changes the password, takes the new identity and clears itself', async () => {
    let changed = 0;
    form.changed.subscribe(() => (changed += 1));
    form.current.set('old one');
    form.fresh.set('a new long passphrase');
    form.confirm.set('a new long passphrase');

    const submitting = form.submit();
    const request = http.expectOne('/api/auth/password/');
    expect(request.request.body).toEqual({ current_password: 'old one', new_password: 'a new long passphrase' });
    request.flush(MASTER);
    await submitting;

    expect(changed).toBe(1);
    expect(form.current()).toBe('');
    expect(TestBed.inject(AuthStore).user()?.username).toBe('sara');
  });
});
