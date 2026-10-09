import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, withComponentInputBinding, type Routes } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { ServersStore } from '../../state/servers.store';
import { SERVER } from '../../testing/servers.fixtures';
import { ServerPage } from './server';

const ROUTES: Routes = [
  {
    path: 'servers/:serverId',
    component: ServerPage,
    providers: [ServersStore],
    children: ['', 'backups', 'files', 'environment', 'activity'].map((path) => ({ path, children: [] })),
  },
];

describe('ServerPage', () => {
  let http: HttpTestingController;

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
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl(`/servers/${SERVER.id}/backups`);
    const request = await vi.waitFor(() => http.expectOne(`/api/servers/${SERVER.id}/`));
    request.flush(SERVER);
    await TestBed.inject(ApplicationRef).whenStable();
    harness.detectChanges();

    const tabs = Array.from((harness.routeNativeElement as HTMLElement).querySelectorAll('nav a'));
    const base = `/servers/${SERVER.id}`;
    expect(tabs.map((tab) => tab.getAttribute('href'))).toEqual([
      base,
      `${base}/backups`,
      `${base}/files`,
      `${base}/environment`,
      `${base}/activity`,
    ]);
    expect(tabs.map((tab) => tab.getAttribute('aria-current'))).toEqual([null, 'page', null, null, null]);
  });
});
