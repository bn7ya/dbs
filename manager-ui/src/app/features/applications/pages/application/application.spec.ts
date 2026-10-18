import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MatTabNavBarHarness } from '@angular/material/tabs/testing';
import { provideRouter, type Routes } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Identity } from '@core/auth/data/auth.types';
import { AuthStore } from '@core/auth/state/auth.store';
import { MASTER, OPERATOR, VIEWER } from '@core/auth/testing/identity.fixtures';
import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { ApplicationsStore } from '../../state/applications.store';
import { APPLICATION, SERVER_ID } from '../../testing/applications.fixtures';
import { ApplicationPage } from './application';

const TABS = ['', 'backups', 'schedule', 'files', 'environment', 'deploy', 'terminal', 'activity'];

const ROUTES: Routes = [
  {
    path: 'applications/:applicationId',
    component: ApplicationPage,
    providers: [ApplicationsStore],
    children: TABS.map((path) => ({ path, children: [] })),
  },
];

describe('ApplicationPage', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;

  const show = async (url: string, identity: Identity): Promise<HTMLElement> => {
    const restoring = TestBed.inject(AuthStore).restore();
    http.expectOne('/api/auth/me/').flush(identity);
    await restoring;
    harness = await RouterTestingHarness.create();
    await harness.navigateByUrl(url);
    (await vi.waitFor(() => http.expectOne(`/api/applications/${APPLICATION.id}/`))).flush(APPLICATION);
    await TestBed.inject(ApplicationRef).whenStable();
    harness.detectChanges();
    return harness.routeNativeElement as HTMLElement;
  };

  const links = (page: HTMLElement): (string | null)[] =>
    Array.from(page.querySelectorAll('nav a'), (tab) => tab.getAttribute('href'));

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [
        provideRouter(ROUTES),
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    TestBed.inject(LocaleStore).register({ en, ar });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it('heads the page with the name, its server and where it runs, and links every tab', async () => {
    const page = await show(`/applications/${APPLICATION.id}/schedule`, MASTER);

    expect(page.querySelector('h1')?.textContent?.trim()).toBe('shop');
    expect(page.querySelector(`header a[href="/servers/${SERVER_ID}"]`)?.textContent).toContain('Production web');
    expect(page.querySelector('app-where-it-runs')?.textContent).toContain('Compose service, Docker');
    const base = `/applications/${APPLICATION.id}`;
    expect(links(page)).toEqual([base, ...TABS.slice(1).map((tab) => `${base}/${tab}`)]);
    const bar = await TestbedHarnessEnvironment.loader(harness.fixture).getHarness(MatTabNavBarHarness);
    expect(await Promise.all((await bar.getLinks()).map((link) => link.isActive()))).toEqual([
      false,
      false,
      true,
      false,
      false,
      false,
      false,
      false,
    ]);
  });

  it('leaves the terminal tab out for a role that may not open a shell', async () => {
    const page = await show(`/applications/${APPLICATION.id}`, OPERATOR);

    expect(links(page)).not.toContain(`/applications/${APPLICATION.id}/terminal`);
    expect(links(page)).toHaveLength(TABS.length - 1);
  });

  it('leaves the deploy and terminal tabs out for a role that may not rehearse a deploy', async () => {
    const page = await show(`/applications/${APPLICATION.id}`, VIEWER);

    expect(links(page)).not.toContain(`/applications/${APPLICATION.id}/deploy`);
    expect(links(page)).toHaveLength(TABS.length - 2);
  });

  it('says when the application is gone', async () => {
    const restoring = TestBed.inject(AuthStore).restore();
    http.expectOne('/api/auth/me/').flush(MASTER);
    await restoring;
    harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/applications/gone');
    (await vi.waitFor(() => http.expectOne('/api/applications/gone/'))).flush(
      { error: { code: 'not_found', message: 'Server prose' } },
      { status: 404, statusText: 'Not Found' },
    );
    await TestBed.inject(ApplicationRef).whenStable();
    harness.detectChanges();

    expect((harness.routeNativeElement as HTMLElement).textContent).toContain('Application not found');
  });
});
