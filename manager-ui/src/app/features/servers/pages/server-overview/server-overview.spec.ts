import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import type { Type } from '@angular/core';
import { ApplicationRef } from '@angular/core';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';

import { VIEWER } from '@core/auth/testing/identity.fixtures';
import { AuthStore } from '@core/auth/state/auth.store';
import { errorInterceptor } from '@core/http/error.interceptor';
import { errorText } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { Dialogs } from '@shared/dialogs/dialogs';
import type { DialogOptions } from '@shared/dialogs/dialogs.types';
import type { PasswordPromptData } from '@shared/password-prompt/password-prompt.types';
import { Toaster } from '@shared/toaster/toaster';
import type { Server } from '../../data/servers.types';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { ServersStore } from '../../state/servers.store';
import { SERVER, SUMMARY, pageOf } from '../../testing/servers.fixtures';
import { ServerOverviewPage } from './server-overview';

const DETAIL = `/api/servers/${SERVER.id}/`;

const TWIN: Server = { ...SERVER, id: '0f3c2b9e-1111-4c4f-9a43-7b1d2f0c0002', name: 'Web again' };

describe('ServerOverviewPage', () => {
  let http: HttpTestingController;
  let fixture: ComponentFixture<ServerOverviewPage>;
  let typed: string[];
  let prompted: Mock<(component: Type<unknown>, options: DialogOptions<PasswordPromptData>) => Promise<true | undefined>>;

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const html = (): HTMLElement => {
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  };

  const show = async (server: Server, twins: readonly Server[] = []): Promise<ServerOverviewPage> => {
    const store = TestBed.inject(ServersStore);
    fixture = TestBed.createComponent(ServerOverviewPage);
    store.select(server.id);
    TestBed.tick();
    http.expectOne(`/api/servers/${server.id}/`).flush(server);
    const search = await vi.waitFor(() => {
      TestBed.tick();
      return http.expectOne((request) => request.url === '/api/servers/');
    });
    search.flush(pageOf([SUMMARY, ...twins.map((twin) => ({ ...SUMMARY, id: twin.id, name: twin.name }))]));
    for (const twin of twins) {
      (await vi.waitFor(() => http.expectOne(`/api/servers/${twin.id}/`))).flush(twin);
    }
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
    TestBed.overrideComponent(ServerOverviewPage, {
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
        ServersStore,
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

  it('shows what the last check found: the system, each engine and the timeout command', async () => {
    await show(SERVER);

    const page = html().textContent ?? '';
    expect(page).toContain('Linux 6.8.0');
    expect(page).toContain('27.3.1');
    expect(page).toContain('2.29.7');
    expect(page).toContain('Not installed');
    expect(page).not.toContain('Another server here is the same machine');
  });

  it('offers to merge into another record of the same machine, behind the password', async () => {
    const page = await show(SERVER, [TWIN]);
    expect(html().textContent).toContain('Another server here is the same machine');
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);

    typed = ['hunter2'];
    const merging = page.merge(TWIN);
    const request = await vi.waitFor(() => http.expectOne(`${DETAIL}merge/`));
    expect(request.request.body).toEqual({ into: TWIN.id, account_password: 'hunter2' });
    request.flush(TWIN);
    await merging;

    expect(prompted.mock.calls[0][1].data).toMatchObject({ bodyValues: { name: '⁨Production web⁩', into: '⁨Web again⁩' } });
    expect(navigate).toHaveBeenCalledWith(['/servers', TWIN.id]);
  });

  it('offers to move the server onto another one', async () => {
    await show(SERVER);

    const link = Array.from(html().querySelectorAll('a')).find((found) => found.textContent?.includes('Move to another server'));
    expect(link?.getAttribute('href')).toBe(`/servers/${SERVER.id}/move`);
    expect(html().textContent).toContain('This server keeps running untouched.');
  });

  it('offers no move to a role that may not even plan one', async () => {
    const restoring = TestBed.inject(AuthStore).restore();
    http.expectOne('/api/auth/me/').flush(VIEWER);
    await restoring;

    await show(SERVER);

    expect(html().textContent).not.toContain('Move to another server');
  });

  it('shows the public key of a key server on request, and none for a password server', async () => {
    const page = await show(SERVER);

    const reading = page.togglePublicKey();
    http.expectOne(`${DETAIL}public-key/`).flush({ public_key: 'ssh-ed25519 AAAA dbs' });
    await reading;
    expect(html().querySelector('textarea')?.value).toBe('ssh-ed25519 AAAA dbs');
    expect(html().textContent).toContain('~deploy/.ssh/authorized_keys');

    await page.togglePublicKey();
    expect(html().querySelector('textarea')).toBeNull();
  });

  it('has no public key card for a server that signs in with a password', async () => {
    await show({ ...SERVER, auth_method: 'password', has_private_key: false, has_password: true });

    expect(html().textContent).not.toContain('Show the public key');
  });

  it('reads a refused delete as "remove its applications first"', async () => {
    const page = await show(SERVER);

    typed = ['hunter2'];
    const removing = page.remove();
    (await vi.waitFor(() => http.expectOne(DETAIL))).flush(
      { error: { code: 'server_has_applications', message: 'Server prose' } },
      { status: 409, statusText: 'Conflict' },
    );
    await removing;

    const data = prompted.mock.calls[0][1].data;
    expect(errorText(TestBed.inject(LocaleStore), data?.error() ?? null)).toBe(
      'This server still runs applications. Remove its applications first, or merge it into another server.',
    );
  });
});
