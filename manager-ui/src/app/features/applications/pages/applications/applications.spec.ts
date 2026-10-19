import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, type TestRequest } from '@angular/common/http/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MatButtonHarness } from '@angular/material/button/testing';
import { MatTableHarness } from '@angular/material/table/testing';
import { provideRouter, type Routes } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Identity } from '@core/auth/data/auth.types';
import { AuthStore } from '@core/auth/state/auth.store';
import { MASTER, OPERATOR } from '@core/auth/testing/identity.fixtures';
import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import type { ApplicationSummary } from '../../data/applications.types';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { ApplicationsStore } from '../../state/applications.store';
import { SERVER_ID, SUMMARY, pageOf } from '../../testing/applications.fixtures';
import { ApplicationsPage } from './applications';

const ROUTES: Routes = [
  {
    path: 'applications',
    providers: [ApplicationsStore],
    component: ApplicationsPage,
  },
  {
    path: 'servers/:serverId',
    children: [{ path: 'applications', providers: [ApplicationsStore], component: ApplicationsPage }],
  },
];

const CONTAINER: ApplicationSummary = {
  ...SUMMARY,
  id: '7a1d2f0c-2222-4c4f-9a43-0f3c2b9e0002',
  name: 'blog',
  kind: 'container',
  engine: 'podman',
  compose_service: '',
  container_name: 'blog-web',
  last_check_status: 'unknown',
  last_checked_at: null,
};

describe('ApplicationsPage', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;

  const listRequest = (): TestRequest => http.expectOne((request) => request.url === '/api/applications/');

  const show = async (url: string, found: readonly ApplicationSummary[], identity: Identity = MASTER): Promise<HTMLElement> => {
    const restoring = TestBed.inject(AuthStore).restore();
    http.expectOne('/api/auth/me/').flush(identity);
    await restoring;
    harness = await RouterTestingHarness.create();
    await harness.navigateByUrl(url);
    (await vi.waitFor(() => listRequest())).flush(pageOf(found));
    await TestBed.inject(ApplicationRef).whenStable();
    harness.detectChanges();
    return harness.routeNativeElement as HTMLElement;
  };

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter(ROUTES),
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

  it('lists every application with its server and where it runs', async () => {
    const page = await show('/applications', [SUMMARY, CONTAINER]);

    const table = await TestbedHarnessEnvironment.loader(harness.fixture).getHarness(MatTableHarness);
    const columns = await table.getCellTextByColumnName();
    expect(columns['name'].text).toEqual(['shop', 'blog']);
    expect(columns['server'].text).toEqual(['Production web', 'Production web']);
    expect(columns['where'].text).toEqual(['Compose service, Docker web', 'Container, Podman blog-web']);
    expect(columns['status'].text).toEqual(['Ready', 'Not checked']);
    expect(page.querySelector(`a[href="/servers/${SERVER_ID}"]`)).not.toBeNull();
    expect(page.querySelector(`a[href="/applications/${SUMMARY.id}"]`)).not.toBeNull();
    expect(page.querySelector('.fa-cube')).not.toBeNull();
  });

  it('lists one server’s applications on its tab, without the server column, with a way to add one', async () => {
    await show(`/servers/${SERVER_ID}/applications`, [SUMMARY]);

    const table = await TestbedHarnessEnvironment.loader(harness.fixture).getHarness(MatTableHarness);
    expect(Object.keys(await table.getCellTextByColumnName())).toEqual(['name', 'where', 'status', 'lastChecked']);
    const add = await TestbedHarnessEnvironment.loader(harness.fixture).getHarness(
      MatButtonHarness.with({ text: /Add an application/ }),
    );
    expect(await (await add.host()).getAttribute('href')).toBe(`/servers/${SERVER_ID}/applications/new`);
  });

  it('leaves adding an application to a role that may', async () => {
    const page = await show(`/servers/${SERVER_ID}/applications`, [], OPERATOR);

    expect(page.textContent).toContain('No applications on this server yet');
    expect(page.querySelector(`a[href="/servers/${SERVER_ID}/applications/new"]`)).toBeNull();
  });

  it('sends the search to the backend once typing settles', async () => {
    await show('/applications', [SUMMARY]);
    harness.routeDebugElement?.injector.get(ApplicationsStore).setSearch('blog');

    const search = await vi.waitFor(
      () => {
        TestBed.tick();
        return listRequest();
      },
      { timeout: 2000 },
    );
    expect(search.request.params.get('search')).toBe('blog');
    search.flush(pageOf([]));
    await TestBed.inject(ApplicationRef).whenStable();
    harness.detectChanges();

    expect((harness.routeNativeElement as HTMLElement).textContent).toContain('No matching applications');
  });
});
