import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { ApplicationRef } from '@angular/core';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { MatButtonHarness } from '@angular/material/button/testing';
import { MatTableHarness } from '@angular/material/table/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthStore } from '@core/auth/state/auth.store';
import { OPERATOR } from '@core/auth/testing/identity.fixtures';
import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import type { Dashboard } from '../../data/dashboard.types';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { DashboardStore } from '../../state/dashboard.store';
import { DASHBOARD, NOW, SHOP, STAGING, WEB } from '../../testing/dashboard.fixtures';
import { DashboardPage } from './dashboard';

describe('DashboardPage', () => {
  let http: HttpTestingController;
  let fixture: ComponentFixture<DashboardPage>;

  const show = async (answer: Dashboard): Promise<HTMLElement> => {
    fixture = TestBed.createComponent(DashboardPage);
    fixture.detectChanges();
    http.expectOne('/api/dashboard/').flush(answer);
    await TestBed.inject(ApplicationRef).whenStable();
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  };

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(NOW);
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [
        DashboardStore,
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    TestBed.inject(LocaleStore).register({ en, ar });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    vi.useRealTimers();
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it('shows each server with its connection and check, and a card per application', async () => {
    const page = await show(DASHBOARD);

    const sections = Array.from(page.querySelectorAll('section.dashboard__server'));
    expect(sections).toHaveLength(2);
    const [web, staging] = sections.map((section) => section.textContent ?? '');
    expect(web).toContain('Production web');
    expect(web).toContain('web-1.example.com');
    expect(web).toContain('Online');
    expect(staging).toContain('Offline, last seen 3 hours ago');
    expect(sections[0].querySelector('h2 a')?.getAttribute('href')).toBe(`/servers/${WEB.id}`);

    const cards = Array.from(sections[0].querySelectorAll('mat-card'));
    expect(cards).toHaveLength(2);
    const [shop, blog] = cards.map((card) => card.textContent ?? '');
    expect(shop).toContain('Compose service, Docker');
    expect(shop).toContain('Check: Ready');
    expect(shop).toContain('Health: Warning');
    expect(shop).toContain('3 hours ago');
    expect(shop).toContain('Verified');
    expect(shop).toContain('5 MB');
    expect(blog).toContain('On the server');
    expect(blog).toContain('Check: Not checked');
    expect(blog).toContain('Health: No report');
    expect(blog).toContain('None yet');
    expect(blog).toContain('No plan scheduled');
    expect(cards[0].querySelector('a')?.getAttribute('href')).toBe(`/applications/${SHOP.id}`);
    expect(cards[0].querySelector('.fa-cube')).not.toBeNull();
    expect(cards[1].querySelector('.fa-server')).not.toBeNull();
  });

  it('offers adding an application to a server that runs none', async () => {
    const page = await show(DASHBOARD);

    const staging = page.querySelectorAll('section.dashboard__server')[1];
    expect(staging.textContent).toContain('No applications on this server yet.');
    expect(staging.querySelector(`a[href="/servers/${STAGING.id}/applications/new"]`)).not.toBeNull();
  });

  it('adds up the servers, the applications, the storage and the failures of the week', async () => {
    const page = await show(DASHBOARD);

    const figures = Array.from(page.querySelectorAll('.dashboard__total dd'), (each) => each.textContent?.trim());
    expect(figures).toEqual(['2', '2', '5 MB', '3', 'yesterday']);
  });

  it('lists the recent failures with what failed and why', async () => {
    const page = await show(DASHBOARD);

    const table = await TestbedHarnessEnvironment.loader(fixture).getHarness(MatTableHarness);
    const rows = await table.getCellTextByColumnName();
    expect(rows['subject'].text).toEqual(['shop', 'Staging']);
    expect(rows['reason'].text).toEqual(['The server did not answer over SSH.', 'The server did not answer over SSH.']);
    expect(page.querySelector(`td a[href="/applications/${SHOP.id}"]`)).not.toBeNull();
    expect(page.querySelector(`td a[href="/servers/${STAGING.id}"]`)).not.toBeNull();
  });

  it('reminds the developer to export once the last export is a week old or missing', async () => {
    let page = await show(DASHBOARD);
    expect(page.querySelector('app-notice')).toBeNull();
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        DashboardStore,
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    TestBed.inject(LocaleStore).register({ en, ar });
    http = TestBed.inject(HttpTestingController);

    page = await show({ ...DASHBOARD, last_export_at: '2026-09-30T12:00:00Z' });
    const notice = page.querySelector('app-notice');
    expect(notice?.textContent).toContain('Last export: 9 days ago.');
    expect(notice?.querySelector('code')?.textContent).toBe('django_dbs export manager.dbs');
  });

  it('says when nothing was ever exported', async () => {
    const page = await show({ ...DASHBOARD, last_export_at: null });

    expect(page.querySelector('app-notice')?.textContent).toContain('No export yet.');
  });

  it('offers adding the first server when there is none', async () => {
    const page = await show({
      servers: [],
      storage_bytes: 0,
      last_export_at: null,
      recent_failures: [],
      key_store: 'keychain',
    });

    expect(page.querySelector('app-empty-state')?.textContent).toContain('No servers yet');
    const add = await TestbedHarnessEnvironment.loader(fixture).getHarness(
      MatButtonHarness.with({ text: 'Add a server' }),
    );
    expect(await add.getAppearance()).toBe('filled');
    expect(await (await add.host()).getAttribute('href')).toBe('/servers/new');
  });

  it('hides adding a server from a role that cannot add one', async () => {
    const restoring = TestBed.inject(AuthStore).restore();
    http.expectOne('/api/auth/me/').flush(OPERATOR);
    await restoring;

    const page = await show(DASHBOARD);

    expect(page.querySelector('a[href="/servers/new"]')).toBeNull();
    expect(page.querySelector(`a[href="/servers/${STAGING.id}/applications/new"]`)).toBeNull();
    expect(page.querySelectorAll('mat-card')).toHaveLength(2);
  });

  it('warns while the sealing key sits in a file next to the data', async () => {
    const page = await show({ ...DASHBOARD, key_store: 'file' });

    expect(page.textContent).toContain('No system keychain works on this computer');
  });
});
