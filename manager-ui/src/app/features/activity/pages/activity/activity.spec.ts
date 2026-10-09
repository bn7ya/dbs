import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, type TestRequest } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, withComponentInputBinding, type Routes } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Identity } from '@core/auth/data/auth.types';
import { errorInterceptor } from '@core/http/error.interceptor';
import { ENTRY, FAILED, SERVER_ID, pageOf } from '../../testing/activity.fixtures';
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
};

const ROUTES: Routes = [
  { path: 'activity', loadChildren: () => import('../../activity.routes').then((m) => m.routes) },
  {
    path: 'servers/:serverId',
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

  it('lists every server at /activity, under its own title', async () => {
    const page = await show('/activity');

    expect(page.scoped()).toBe(false);
    const request = listRequest();
    expect(request.request.params.has('server')).toBe(false);
    request.flush(pageOf([ENTRY, FAILED]));
    await settle();
    harness.detectChanges();

    expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toContain('Activity');
    expect(page.actionOptions().map((option) => option.value)).toContain('auth.sign_in');
  });

  it('lists one server under its tab, with no title of its own and no sign-in actions', async () => {
    const page = await show(`/servers/${SERVER_ID}/activity`);

    expect(page.scoped()).toBe(true);
    const request = listRequest();
    expect(request.request.params.get('server')).toBe(SERVER_ID);
    request.flush(pageOf([ENTRY]));
    await settle();
    harness.detectChanges();

    expect(harness.routeNativeElement?.querySelector('h1')).toBeNull();
    const scopedCodes = page.actionOptions().map((option) => option.value);
    expect(scopedCodes.some((code) => code.startsWith('auth.') || code.startsWith('manager.'))).toBe(false);
    expect(scopedCodes).toContain('redeploy.run');
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

  it('reads an entry with no actor as scheduled, except a refused sign-in', async () => {
    const page = await show('/activity');
    listRequest().flush(pageOf([]));
    await settle();

    expect(page.scheduled({ ...ENTRY, actor: null })).toBe(true);
    expect(page.scheduled({ ...ENTRY, actor: null, action: 'auth.sign_in_failed', server: null })).toBe(false);
  });
});
