import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, type TestRequest } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, withComponentInputBinding, type Routes } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Identity } from '@core/auth/data/auth.types';
import { MASTER_ACCOUNT } from '@core/auth/testing/identity.fixtures';
import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import { ACTIVITY_ACTIONS } from '../../data/activity.types';
import {
  APPLICATION_ID,
  ENTRY,
  REMOVED,
  SERVER_ENTRY,
  SERVER_ID,
  pageOf,
} from '../../testing/activity.fixtures';
import { ActivityPage } from './activity';

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

const ROUTES: Routes = [
  { path: 'activity', loadChildren: () => import('../../activity.routes').then((m) => m.routes) },
  {
    path: 'servers/:serverId',
    children: [{ path: 'activity', loadChildren: () => import('../../activity.routes').then((m) => m.routes) }],
  },
  {
    path: 'applications/:applicationId',
    children: [{ path: 'activity', loadChildren: () => import('../../activity.routes').then((m) => m.routes) }],
  },
];

describe('ActivityPage', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const show = async (url: string): Promise<ActivityPage> => {
    harness = await RouterTestingHarness.create();
    const navigating = harness.navigateByUrl(url, ActivityPage);
    const me = await vi.waitFor(() => http.expectOne('/api/auth/me/'));
    me.flush(IDENTITY);
    const page = await navigating;
    TestBed.tick();
    return page;
  };

  const listRequest = (): TestRequest => http.expectOne((request) => request.url === '/api/activity/');

  const headers = (): (string | undefined)[] =>
    Array.from(harness.routeNativeElement?.querySelectorAll('th') ?? [], (cell) => cell.textContent?.trim());

  const cells = (row: number, column: number): HTMLElement => {
    const rows = harness.routeNativeElement?.querySelectorAll('tr[mat-row]') ?? [];
    return rows[row].querySelectorAll<HTMLElement>('td')[column];
  };

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
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it('lists everything at /activity, under its own title, with the application and the server of each entry', async () => {
    const page = await show('/activity');

    expect(page.scoped()).toBe(false);
    const request = listRequest();
    expect(request.request.params.has('server')).toBe(false);
    expect(request.request.params.has('application')).toBe(false);
    request.flush(pageOf([ENTRY, SERVER_ENTRY, REMOVED]));
    await settle();
    harness.detectChanges();

    expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toContain('Activity');
    expect(page.actionOptions().map((option) => option.value)).toContain('auth.sign_in');
    expect(headers()).toEqual(['When', 'Action', 'Status', 'Application', 'Server', 'Target', 'By', 'IP address']);

    const application = cells(0, 3).querySelector('a');
    expect(application?.getAttribute('href')).toBe(`/applications/${APPLICATION_ID}`);
    expect(application?.querySelector('bdi')?.textContent).toBe('Shop');
    const server = cells(0, 4).querySelector('a');
    expect(server?.getAttribute('href')).toBe(`/servers/${SERVER_ID}`);
    expect(server?.querySelector('bdi')?.textContent).toBe('Production web');

    expect(cells(1, 3).querySelector('a')).toBeNull();
    expect(cells(1, 3).textContent?.trim()).toBe('—');
    expect(cells(1, 4).querySelector('a')?.getAttribute('href')).toBe(`/servers/${SERVER_ID}`);

    expect(cells(2, 3).querySelector('a')).toBeNull();
    expect(cells(2, 3).textContent).toContain('Old shop');
    expect(cells(2, 3).textContent).toContain('Removed');
    expect(cells(2, 4).querySelector('a')).toBeNull();
    expect(cells(2, 4).textContent).toContain('Retired web');
    expect(cells(2, 4).textContent).toContain('Deleted');
  });

  it('lists one server and its applications under its tab, with no title of its own and no sign-in actions', async () => {
    const page = await show(`/servers/${SERVER_ID}/activity`);

    expect(page.scoped()).toBe(true);
    const request = listRequest();
    expect(request.request.params.get('server')).toBe(SERVER_ID);
    expect(request.request.params.has('application')).toBe(false);
    request.flush(pageOf([ENTRY, SERVER_ENTRY]));
    await settle();
    harness.detectChanges();

    expect(harness.routeNativeElement?.querySelector('h1')).toBeNull();
    const scopedCodes = page.actionOptions().map((option) => option.value);
    expect(scopedCodes.some((code) => code.startsWith('auth.') || code.startsWith('account.'))).toBe(false);
    expect(scopedCodes.some((code) => code.startsWith('manager.'))).toBe(false);
    expect(scopedCodes).toContain('redeploy.run');
    expect(headers()).toEqual(['When', 'Action', 'Status', 'Application', 'Target', 'By', 'IP address']);
    expect(cells(0, 3).querySelector('a')?.getAttribute('href')).toBe(`/applications/${APPLICATION_ID}`);
  });

  it('lists one application under its tab, with no server or application column and no sign-in actions', async () => {
    const page = await show(`/applications/${APPLICATION_ID}/activity`);

    expect(page.scoped()).toBe(true);
    const request = listRequest();
    expect(request.request.params.get('application')).toBe(APPLICATION_ID);
    expect(request.request.params.has('server')).toBe(false);
    request.flush(pageOf([ENTRY]));
    await settle();
    harness.detectChanges();

    expect(harness.routeNativeElement?.querySelector('h1')).toBeNull();
    const scopedCodes = page.actionOptions().map((option) => option.value);
    expect(scopedCodes.some((code) => code.startsWith('auth.') || code.startsWith('manager.'))).toBe(false);
    expect(scopedCodes).toContain('deploy.git_pull');
    expect(headers()).toEqual(['When', 'Action', 'Status', 'Target', 'By', 'IP address']);
  });

  it('says what an empty tab would list, for a server and for an application', async () => {
    await show(`/applications/${APPLICATION_ID}/activity`);
    listRequest().flush(pageOf([], 0));
    await settle();
    harness.detectChanges();

    expect(harness.routeNativeElement?.querySelector('app-empty-state')?.textContent).toContain(
      'Actions taken on this application are listed here.',
    );

    await harness.navigateByUrl(`/servers/${SERVER_ID}/activity`);
    TestBed.tick();
    listRequest().flush(pageOf([], 0));
    await settle();
    harness.detectChanges();

    expect(harness.routeNativeElement?.querySelector('app-empty-state')?.textContent).toContain(
      'Actions taken on this server and its applications are listed here.',
    );
  });

  it('names a known action and shows an unknown one as its code', async () => {
    const page = await show('/activity');
    listRequest().flush(pageOf([]));
    await settle();

    expect(page.actionLabel('server.check')).toBe('Connection check');
    expect(page.actionLabel('backup.run')).toBe('Run backup plan');
    expect(page.actionLabel('plan.create')).toBe('Add backup plan');
    expect(page.actionLabel('server.passphrase_capture')).toBe('Save backup passphrase');
    expect(page.actionLabel('redeploy.final_check')).toBe('Move: check again');
    expect(page.actionLabel('manager.export')).toBe('Export DBS data');
    expect(page.actionLabel('example.unknown')).toBe('example.unknown');
  });

  it('names every action it offers, in English and in Arabic', async () => {
    const page = await show('/activity');
    listRequest().flush(pageOf([]));
    await settle();
    const locale = TestBed.inject(LocaleStore);

    expect(ACTIVITY_ACTIONS.filter((code) => page.actionLabel(code) === code)).toEqual([]);
    expect(page.actionLabel('account.two_factor_reset')).toBe('Reset two-factor sign-in');
    expect(page.actionLabel('auth.recovery_code_used')).toBe('Sign in with a recovery code');

    locale.setLocale('ar');

    expect(ACTIVITY_ACTIONS.filter((code) => page.actionLabel(code) === code)).toEqual([]);
    expect(page.actionLabel('account.master')).toBe('تعيين الحساب الرئيسي');
  });

  it('offers each action once, under a name no other one has, in English and in Arabic', async () => {
    const page = await show('/activity');
    listRequest().flush(pageOf([]));
    await settle();
    const labels = () => page.actionOptions().map((option) => option.label);

    expect(new Set(labels()).size).toBe(labels().length);
    expect(labels().filter((label) => label === 'Show backup passphrase')).toHaveLength(1);
    expect(page.actionLabel('server.passphrase_reveal')).toBe('Show backup passphrase');

    TestBed.inject(LocaleStore).setLocale('ar');

    expect(new Set(labels()).size).toBe(labels().length);
  });

  it('shows a backup kept on the server as its own outcome, not a failure', async () => {
    const page = await show('/activity');
    const kept = { ...ENTRY, id: 3, action: 'backup.take', detail: { outcome: 'kept_on_server', pulled: 0 } };
    listRequest().flush(pageOf([kept, ENTRY]));
    await settle();
    harness.detectChanges();

    expect(page.keptOnServer(kept)).toBe(true);
    expect(page.keptOnServer(ENTRY)).toBe(false);
    expect(page.keptOnServer({ ...kept, status: 'failed' })).toBe(false);
    const text = harness.routeNativeElement?.textContent ?? '';
    expect(text).toContain('Kept on the server');
    expect(text).toContain('Collected at the next connection');
  });

  it('reads an entry with no actor as scheduled, except a refused sign-in', async () => {
    const page = await show('/activity');
    listRequest().flush(pageOf([]));
    await settle();

    expect(page.scheduled({ ...ENTRY, actor: null })).toBe(true);
    expect(page.scheduled({ ...ENTRY, actor: null, action: 'auth.sign_in_failed', server: null })).toBe(false);
  });
});
