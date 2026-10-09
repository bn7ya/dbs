import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { ApplicationRef } from '@angular/core';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { MatButtonHarness } from '@angular/material/button/testing';
import { MatTableHarness } from '@angular/material/table/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import type { Dashboard } from '../../data/dashboard.types';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { DashboardStore } from '../../state/dashboard.store';
import { DASHBOARD, NOW } from '../../testing/dashboard.fixtures';
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

  it('shows each server with its check, health, last backup, next run, failures and storage', async () => {
    const page = await show(DASHBOARD);

    const cards = Array.from(page.querySelectorAll('mat-card'));
    expect(cards).toHaveLength(2);
    const [web, staging] = cards.map((card) => card.textContent ?? '');
    expect(web).toContain('Production web');
    expect(web).toContain('Check: Ready');
    expect(web).toContain('Health: Warning');
    expect(web).toContain('3 hours ago');
    expect(web).toContain('5 MB');
    expect(staging).toContain('Check: Not checked');
    expect(staging).toContain('Health: No report');
    expect(staging).toContain('None yet');
    expect(staging).toContain('No plan scheduled');
    expect(cards[0].querySelector('a')?.getAttribute('href')).toBe(`/servers/${DASHBOARD.servers[0].id}`);
  });

  it('adds up the servers, the storage and the failures of the week', async () => {
    const page = await show(DASHBOARD);

    const figures = Array.from(page.querySelectorAll('.dashboard__total dd'), (each) => each.textContent?.trim());
    expect(figures).toEqual(['2', '5 MB', '3', 'yesterday']);
  });

  it('lists the recent failures with their reasons', async () => {
    await show(DASHBOARD);

    const table = await TestbedHarnessEnvironment.loader(fixture).getHarness(MatTableHarness);
    const rows = await table.getCellTextByColumnName();
    expect(rows['server'].text).toEqual(['Production web']);
    expect(rows['reason'].text).toEqual(['The server did not answer over SSH.']);
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
    const page = await show({ servers: [], storage_bytes: 0, last_export_at: null, recent_failures: [] });

    expect(page.querySelector('app-empty-state')?.textContent).toContain('No servers yet');
    const add = await TestbedHarnessEnvironment.loader(fixture).getHarness(
      MatButtonHarness.with({ text: 'Add a server' }),
    );
    expect(await add.getAppearance()).toBe('filled');
    expect(await (await add.host()).getAttribute('href')).toBe('/servers/new');
  });
});
