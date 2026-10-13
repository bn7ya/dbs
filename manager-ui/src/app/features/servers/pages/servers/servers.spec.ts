import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, type TestRequest } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, withComponentInputBinding, type Routes } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';

import type { Identity } from '@core/auth/data/auth.types';
import { MASTER_ACCOUNT, OPERATOR } from '@core/auth/testing/identity.fixtures';
import { errorInterceptor } from '@core/http/error.interceptor';
import { Confirmation } from '@shared/confirm/confirmation';
import { Toaster } from '@shared/toaster/toaster';
import type { ToastMessage } from '@shared/toaster/toaster.types';
import type { HostKeyConfirmation } from '../../data/servers.types';
import { HOST_KEY_CONFIRMATION, SUMMARY, pageOf } from '../../testing/servers.fixtures';
import { ServersPage } from './servers';

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
  ...MASTER_ACCOUNT,
};

const ROUTES: Routes = [{ path: 'servers', loadChildren: () => import('../../servers.routes').then((m) => m.routes) }];

const ADDRESS = `${HOST_KEY_CONFIRMATION.host}:${HOST_KEY_CONFIRMATION.port}`;

describe('ServersPage', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;
  let toasts: MockInstance<(message: ToastMessage) => void>;

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const hostKeysRequest = (): TestRequest =>
    http.expectOne((request) => request.url === '/api/servers/host-keys/');

  const showWith = async (
    pending: readonly HostKeyConfirmation[],
    identity: Identity = IDENTITY,
  ): Promise<ServersPage> => {
    harness = await RouterTestingHarness.create();
    const navigating = harness.navigateByUrl('/servers', ServersPage);
    (await vi.waitFor(() => http.expectOne('/api/auth/me/'))).flush(identity);
    const page = await navigating;
    TestBed.tick();
    hostKeysRequest().flush(pageOf(pending));
    http.expectOne((request) => request.url === '/api/servers/').flush(pageOf([SUMMARY]));
    await settle();
    harness.detectChanges();
    return page;
  };

  const element = (): HTMLElement => harness.routeNativeElement as HTMLElement;
  const buttonLabelled = (label: string): HTMLButtonElement | null =>
    element().querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`);

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter(ROUTES, withComponentInputBinding()),
      ],
    });
    http = TestBed.inject(HttpTestingController);
    toasts = vi.spyOn(TestBed.inject(Toaster), 'add').mockReturnValue(undefined);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('shows no card while no host key awaits a person', async () => {
    await showWith([]);

    expect(element().textContent).not.toContain('Host keys awaiting confirmation');
  });

  it('shows each host key awaiting a person, with where it is, its fingerprint and how to compare it', async () => {
    await showWith([HOST_KEY_CONFIRMATION]);

    const card = element().querySelector('.servers__pending');
    expect(element().textContent).toContain('Host keys awaiting confirmation');
    expect(card?.querySelector('h3')?.textContent?.trim()).toBe(ADDRESS);
    expect(card?.textContent).toContain(HOST_KEY_CONFIRMATION.fingerprint);
    expect(card?.textContent).toContain('ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub');
    expect(buttonLabelled(`Confirm the host key of ${ADDRESS}`)).not.toBeNull();
    expect(buttonLabelled(`Reject the host key of ${ADDRESS}`)?.classList).toContain('app-danger');
  });

  it('leaves a host key to an account that may add servers', async () => {
    await showWith([HOST_KEY_CONFIRMATION], OPERATOR);

    expect(element().textContent).not.toContain('Host keys awaiting confirmation');
    expect(buttonLabelled(`Confirm the host key of ${ADDRESS}`)).toBeNull();
    expect(buttonLabelled(`Reject the host key of ${ADDRESS}`)).toBeNull();
  });

  it('confirms a host key only after asking, then says Claude can add the server', async () => {
    const page = await showWith([HOST_KEY_CONFIRMATION]);
    const ask = vi.spyOn(TestBed.inject(Confirmation), 'ask').mockResolvedValueOnce(false).mockResolvedValueOnce(true);

    await page.confirmHostKey(HOST_KEY_CONFIRMATION);
    expect(ask).toHaveBeenCalledWith(expect.objectContaining({ title: `Confirm the host key of ⁦${ADDRESS}⁩?` }));
    http.expectNone(`/api/servers/host-keys/${HOST_KEY_CONFIRMATION.id}/confirm/`);

    const confirming = page.confirmHostKey(HOST_KEY_CONFIRMATION);
    (await vi.waitFor(() => http.expectOne(`/api/servers/host-keys/${HOST_KEY_CONFIRMATION.id}/confirm/`))).flush({
      ...HOST_KEY_CONFIRMATION,
      status: 'confirmed',
    });
    await confirming;
    TestBed.tick();
    hostKeysRequest().flush(pageOf([]));
    await settle();
    harness.detectChanges();

    expect(toasts).toHaveBeenCalledWith({
      severity: 'success',
      summary: 'Host key confirmed. Claude can add the server now.',
    });
    expect(element().querySelector('.servers__pending')).toBeNull();
  });

  it('rejects a host key at once, and says why when it could not', async () => {
    await showWith([HOST_KEY_CONFIRMATION]);

    buttonLabelled(`Reject the host key of ${ADDRESS}`)?.click();
    (await vi.waitFor(() => http.expectOne(`/api/servers/host-keys/${HOST_KEY_CONFIRMATION.id}/reject/`))).flush(
      { error: { code: 'host_key_confirmation_missing', message: 'Server prose' } },
      { status: 404, statusText: 'Not Found' },
    );
    (await vi.waitFor(() => hostKeysRequest())).flush(pageOf([]));
    await settle();

    expect(toasts).toHaveBeenCalledWith({ severity: 'danger', summary: 'This request has expired.' });
  });
});
