import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CsrfToken } from './csrf-token';
import { csrfInterceptor } from './csrf.interceptor';

describe('csrfInterceptor', () => {
  let http: HttpTestingController;
  let client: HttpClient;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(withInterceptors([csrfInterceptor])), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
    client = TestBed.inject(HttpClient);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    document.cookie = 'csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
  });

  it('sends nothing on a safe request', async () => {
    const reading = firstValueFrom(client.get('/api/servers/'));
    const request = http.expectOne('/api/servers/');
    expect(request.request.headers.has('X-CSRFToken')).toBe(false);
    request.flush({});
    await reading;
  });

  it('copies the readable cookie into the header', async () => {
    document.cookie = 'csrftoken=from-cookie; path=/';

    const posting = firstValueFrom(client.post('/api/backups/take/', {}));
    const request = http.expectOne('/api/backups/take/');
    expect(request.request.headers.get('X-CSRFToken')).toBe('from-cookie');
    request.flush({});
    await posting;
  });

  it('uses the token it holds when the cookie cannot be read', async () => {
    TestBed.inject(CsrfToken).hold('held');

    const posting = firstValueFrom(client.post('/api/backups/take/', {}));
    const request = http.expectOne('/api/backups/take/');
    expect(request.request.headers.get('X-CSRFToken')).toBe('held');
    request.flush({});
    await posting;
  });

  it('asks for a token first when it has none, and keeps it', async () => {
    const posting = firstValueFrom(client.post('/api/backups/take/', {}));

    http.expectOne('/api/auth/csrf/').flush({ csrf_token: 'fetched' });
    const request = await vi.waitFor(() => http.expectOne('/api/backups/take/'));
    expect(request.request.headers.get('X-CSRFToken')).toBe('fetched');
    request.flush({});
    await posting;

    expect(TestBed.inject(CsrfToken).value()).toBe('fetched');
  });
});
