import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';

import type { Identity } from '@core/auth/data/auth.types';
import { AuthStore } from '@core/auth/state/auth.store';
import type { ApiError } from './api.types';
import { errorInterceptor } from './error.interceptor';

const IDENTITY: Identity = {
  id: 1,
  username: 'sara',
  email: 'sara@example.com',
  first_name: 'Sara',
  last_name: 'Hassan',
  is_staff: false,
  is_superuser: false,
  groups: [],
  permissions: [],
};

const FILES_URL = '/api/files/0f3c2b9e-1111-4c4f-9a43-7b1d2f0c0001/';

describe('errorInterceptor', () => {
  let http: HttpTestingController;
  let client: HttpClient;
  let auth: AuthStore;
  let navigate: MockInstance<Router['navigate']>;

  const fail = async (url: string, body: string | object, status: number, statusText = 'Error'): Promise<ApiError> => {
    const sending = firstValueFrom(client.get(url));
    http.expectOne(url).flush(body, { status, statusText });
    return sending.then(
      () => {
        throw new Error('the request succeeded');
      },
      (error: unknown) => error as ApiError,
    );
  };

  const envelope = (code: string): object => ({ error: { code, message: 'Server prose' } });

  const signIn = async (): Promise<void> => {
    const restoring = auth.restore();
    http.expectOne('/api/auth/me/').flush(IDENTITY);
    await restoring;
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(withInterceptors([errorInterceptor])), provideHttpClientTesting(), provideRouter([])],
    });
    http = TestBed.inject(HttpTestingController);
    client = TestBed.inject(HttpClient);
    auth = TestBed.inject(AuthStore);
    navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    vi.restoreAllMocks();
  });

  describe('a session that is gone', () => {
    it('forgets who was signed in and sends them to sign in, on a 403 not_authenticated', async () => {
      await signIn();

      const error = await fail(FILES_URL, envelope('not_authenticated'), 403, 'Forbidden');

      expect(error.code).toBe('not_authenticated');
      expect(auth.isAuthenticated()).toBe(false);
      expect(navigate).toHaveBeenCalledOnce();
      expect(navigate.mock.lastCall?.[0]).toEqual(['/sign-in']);
    });

    it('does the same on a 401 authentication_failed', async () => {
      await signIn();

      await fail(FILES_URL, envelope('authentication_failed'), 401, 'Unauthorized');

      expect(auth.isAuthenticated()).toBe(false);
      expect(navigate).toHaveBeenCalledOnce();
    });

    it('leaves the sign-in endpoints alone: there a refusal is about the credentials', async () => {
      const error = await fail('/api/auth/login/', envelope('authentication_failed'), 403, 'Forbidden');

      expect(error.code).toBe('authentication_failed');
      expect(navigate).not.toHaveBeenCalled();
    });
  });

  describe('a refusal that is about the request, not the session', () => {
    it.each(['path_outside_roots', 'remote_permission_denied', 'permission_denied'])(
      'hands a 403 %s to the caller and keeps the user where they are',
      async (code) => {
        await signIn();

        const error = await fail(FILES_URL, envelope(code), 403, 'Forbidden');

        expect(error.code).toBe(code);
        expect(auth.isAuthenticated()).toBe(true);
        expect(navigate).not.toHaveBeenCalled();
      },
    );

    it('keeps the user where they are on a 403 with no envelope', async () => {
      await signIn();

      const error = await fail(FILES_URL, '<html><body>403 Forbidden</body></html>', 403, 'Forbidden');

      expect(error.code).toBe('unknown');
      expect(auth.isAuthenticated()).toBe(true);
      expect(navigate).not.toHaveBeenCalled();
    });
  });

  describe('a failure with no envelope', () => {
    it('reads as not_found when Django rejected the URL', async () => {
      const error = await fail(FILES_URL, '<html>Not Found</html>', 404, 'Not Found');
      expect(error.code).toBe('not_found');
    });

    it('reads as upload_too_large when the proxy refused the body', async () => {
      const error = await fail(FILES_URL, '<html>413 Request Entity Too Large</html>', 413, 'Too Large');
      expect(error.code).toBe('upload_too_large');
    });

    it('reads as network when nothing answered', async () => {
      const sending = firstValueFrom(client.get(FILES_URL));
      http.expectOne(FILES_URL).error(new ProgressEvent('error'), { status: 0, statusText: '' });

      await expect(sending).rejects.toMatchObject({ code: 'network' });
      expect(navigate).not.toHaveBeenCalled();
    });
  });
});
