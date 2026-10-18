import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { TestBed } from '@angular/core/testing';
import { MatTabNavBarHarness } from '@angular/material/tabs/testing';
import { provideRouter, withComponentInputBinding, type Routes } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Identity } from '@core/auth/data/auth.types';
import { AuthStore } from '@core/auth/state/auth.store';
import { MASTER, OPERATOR } from '@core/auth/testing/identity.fixtures';
import { errorInterceptor } from '@core/http/error.interceptor';
import { ServersStore } from '../../state/servers.store';
import { SERVER } from '../../testing/servers.fixtures';
import { ServerPage } from './server';

const ROUTES: Routes = [
  {
    path: 'servers/:serverId',
    component: ServerPage,
    providers: [ServersStore],
    children: ['', 'applications', 'terminal', 'activity'].map((path) => ({ path, children: [] })),
  },
];

describe('ServerPage', () => {
  let http: HttpTestingController;

  const show = async (url: string, identity: Identity): Promise<RouterTestingHarness> => {
    const restoring = TestBed.inject(AuthStore).restore();
    http.expectOne('/api/auth/me/').flush(identity);
    await restoring;
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl(url);
    (await vi.waitFor(() => http.expectOne(`/api/servers/${SERVER.id}/`))).flush(SERVER);
    await TestBed.inject(ApplicationRef).whenStable();
    harness.detectChanges();
    return harness;
  };

  const links = (harness: RouterTestingHarness): (string | null)[] =>
    Array.from((harness.routeNativeElement as HTMLElement).querySelectorAll('nav a'), (tab) => tab.getAttribute('href'));

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [
        provideRouter(ROUTES, withComponentInputBinding()),
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it('links each tab to its section, and the overview to the server page itself, from any tab', async () => {
    const harness = await show(`/servers/${SERVER.id}/applications`, MASTER);

    expect((harness.routeNativeElement as HTMLElement).querySelector('app-connection-dot')?.textContent).toContain(
      'Online',
    );
    const base = `/servers/${SERVER.id}`;
    expect(links(harness)).toEqual([base, `${base}/applications`, `${base}/terminal`, `${base}/activity`]);
    const bar = await TestbedHarnessEnvironment.loader(harness.fixture).getHarness(MatTabNavBarHarness);
    expect(await Promise.all((await bar.getLinks()).map((link) => link.isActive()))).toEqual([false, true, false, false]);
  });

  it('leaves the terminal tab out for a role that may not open a shell', async () => {
    const harness = await show(`/servers/${SERVER.id}`, OPERATOR);

    const base = `/servers/${SERVER.id}`;
    expect(links(harness)).toEqual([base, `${base}/applications`, `${base}/activity`]);
  });
});
