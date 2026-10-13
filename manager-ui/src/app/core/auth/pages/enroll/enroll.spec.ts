import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { AuthStore } from '../../state/auth.store';
import { MASTER } from '../../testing/identity.fixtures';
import { EnrollPage } from './enroll';

const ENROLLMENT = {
  secret: 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP',
  uri: 'otpauth://totp/DBS%20manager%3Asara?secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP&issuer=DBS%20manager',
  issuer: 'DBS manager',
  username: 'sara',
};

describe('EnrollPage', () => {
  let http: HttpTestingController;
  let fixture: ComponentFixture<EnrollPage>;

  const settled = async (): Promise<HTMLElement> => {
    await TestBed.inject(ApplicationRef).whenStable();
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  };

  beforeEach(async () => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    http = TestBed.inject(HttpTestingController);
    TestBed.inject(AuthStore).begin('enroll');
    fixture = TestBed.createComponent(EnrollPage);
    fixture.detectChanges();
    http.expectOne('/api/auth/two-factor/enrollment/').flush(ENROLLMENT);
    await settled();
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('shows the QR code and the key in groups of four', async () => {
    const page = await settled();

    const image = page.querySelector('app-qr-code img') as HTMLImageElement;
    expect(image.src.startsWith('data:image/gif;base64,')).toBe(true);
    expect(image.alt).toBe('A QR code that adds DBS manager to your authenticator app');
    expect(page.querySelector('code')?.textContent).toBe('JBSW Y3DP EHPK 3PXP JBSW Y3DP EHPK 3PXP');
  });

  it('asks for the code before sending anything', async () => {
    await fixture.componentInstance.submit();
    const page = await settled();

    expect(page.querySelector('mat-error')?.textContent?.trim()).toBe('Enter the code.');
    http.expectNone('/api/auth/two-factor/enrollment/confirm/');
  });

  it('shows a refused code under its field', async () => {
    fixture.componentInstance.code.set('000000');
    const submitting = fixture.componentInstance.submit();
    http
      .expectOne('/api/auth/two-factor/enrollment/confirm/')
      .flush({ error: { code: 'invalid_code', message: 'No' } }, { status: 400, statusText: 'Bad Request' });
    await submitting;
    const page = await settled();

    expect(page.querySelector('mat-error')?.textContent?.trim()).toBe('The code is not right, or it was already used.');
  });

  it('shows the recovery codes once, then goes on', async () => {
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    fixture.componentInstance.code.set('123456');
    const submitting = fixture.componentInstance.submit();
    const confirm = http.expectOne('/api/auth/two-factor/enrollment/confirm/');
    expect(confirm.request.body).toEqual({ code: '123456' });
    confirm.flush({ identity: MASTER, recovery_codes: ['abcde-23456', 'fghjk-78923'] });
    await submitting;
    const page = await settled();

    expect(Array.from(page.querySelectorAll('li code')).map((node) => node.textContent)).toEqual([
      'abcde-23456',
      'fghjk-78923',
    ]);
    await fixture.componentInstance.continue();

    expect(TestBed.inject(AuthStore).recoveryCodes()).toBeNull();
    expect(navigate).toHaveBeenCalledWith('/');
  });
});
