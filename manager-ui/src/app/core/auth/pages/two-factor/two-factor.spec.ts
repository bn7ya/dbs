import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { AuthStore } from '../../state/auth.store';
import { MASTER } from '../../testing/identity.fixtures';
import { TwoFactorPage } from './two-factor';

describe('TwoFactorPage', () => {
  let http: HttpTestingController;
  let fixture: ComponentFixture<TwoFactorPage>;
  let page: TwoFactorPage;

  const rendered = async (): Promise<HTMLElement> => {
    await TestBed.inject(ApplicationRef).whenStable();
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  };

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { queryParamMap: convertToParamMap({ next: '/servers' }) } },
        },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    TestBed.inject(AuthStore).begin('code');
    fixture = TestBed.createComponent(TwoFactorPage);
    page = fixture.componentInstance;
    fixture.detectChanges();
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('signs in with the code and follows the way back', async () => {
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    page.code.set(' 123 456 ');

    const submitting = page.submit();
    const request = http.expectOne('/api/auth/two-factor/');
    expect(request.request.body).toEqual({ code: '123 456' });
    request.flush(MASTER);
    await submitting;

    expect(navigate).toHaveBeenCalledWith('/servers');
  });

  it('takes a recovery code instead when asked', async () => {
    page.switchFactor();
    const html = await rendered();
    expect(html.textContent).toContain('Recovery code');

    page.code.set('abcde-23456');
    const submitting = page.submit();
    const request = http.expectOne('/api/auth/two-factor/');
    expect(request.request.body).toEqual({ recovery_code: 'abcde-23456' });
    request.flush({ error: { code: 'invalid_code', message: 'No' } }, { status: 400, statusText: 'Bad Request' });
    await submitting;

    expect((await rendered()).querySelector('mat-error')?.textContent?.trim()).toBe(
      'The code is not right, or it was already used.',
    );
  });

  it('offers to sign in again once the waiting sign-in expired', async () => {
    page.code.set('123456');
    const submitting = page.submit();
    http
      .expectOne('/api/auth/two-factor/')
      .flush({ error: { code: 'sign_in_expired', message: 'Late' } }, { status: 403, statusText: 'Forbidden' });
    await submitting;

    const html = await rendered();
    expect(html.textContent).toContain('The sign-in took too long. Sign in again.');
    expect(html.querySelector('form')).toBeNull();
  });
});
