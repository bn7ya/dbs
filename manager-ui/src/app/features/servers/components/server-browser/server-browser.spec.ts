import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import type { RemoteEntry, RemoteFolder } from '../../data/servers.types';
import { SERVER } from '../../testing/servers.fixtures';
import { ServerBrowser } from './server-browser';
import type { ServerBrowserData } from './server-browser.types';

const BROWSE = `/api/servers/${SERVER.id}/browse/`;

function entry(name: string, kind: RemoteEntry['kind'], folder = '/home/deploy'): RemoteEntry {
  return { name, path: `${folder}/${name}`, kind, size: kind === 'file' ? 12 : null, modified: null };
}

function folderOf(path: string, results: readonly RemoteEntry[], project = false): RemoteFolder {
  const cut = path.lastIndexOf('/');
  return {
    path,
    parent: path === '/' ? null : path.slice(0, cut) || '/',
    home: '/home/deploy',
    project,
    truncated: false,
    count: results.length,
    next: null,
    previous: null,
    results,
  };
}

const HOME = folderOf('/home/deploy', [entry('app', 'folder'), entry('notes.txt', 'file')]);
const APP = folderOf(
  '/home/deploy/app',
  [entry('shop', 'folder', '/home/deploy/app'), entry('.env', 'file', '/home/deploy/app'), entry('manage.py', 'file', '/home/deploy/app')],
  true,
);

describe('ServerBrowser', () => {
  let http: HttpTestingController;
  let close: ReturnType<typeof vi.fn>;
  let fixture: ComponentFixture<ServerBrowser>;
  let browser: ServerBrowser;
  let payload: { data: ServerBrowserData };

  const rendered = (): HTMLElement => {
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  };

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const answer = async (folder: RemoteFolder, path: string | null): Promise<void> => {
    TestBed.tick();
    const request = http.expectOne((each) => each.url === BROWSE);
    expect(request.request.params.get('path')).toBe(path);
    request.flush(folder);
    await settle();
  };

  const open = (data: Partial<ServerBrowserData> = {}): void => {
    payload.data = { ...payload.data, ...data };
    fixture = TestBed.createComponent(ServerBrowser);
    browser = fixture.componentInstance;
  };

  const buttonNamed = (name: string): HTMLButtonElement | undefined =>
    [...rendered().querySelectorAll('button')].find((button) => button.textContent?.trim() === name);

  beforeEach(() => {
    close = vi.fn();
    payload = { data: { serverId: SERVER.id, start: null, mode: 'folder', projects: [] } };
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        { provide: MatDialogRef, useValue: { close } },
        { provide: MAT_DIALOG_DATA, useFactory: () => payload },
      ],
    });
    TestBed.inject(LocaleStore).register({ en, ar });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('opens in the home folder and walks into a folder and back up', async () => {
    open();
    await answer(HOME, null);
    expect(rendered().textContent).toContain('notes.txt');

    browser.go('/home/deploy/app');
    await answer(APP, '/home/deploy/app');
    expect(rendered().textContent).toContain('This folder is a Django project');
    expect(browser.trail().map((crumb) => crumb.name)).toEqual(['/', 'home', 'deploy', 'app']);

    browser.up();
    await answer(HOME, '/home/deploy');
    expect(rendered().textContent).not.toContain('This folder is a Django project');
  });

  it('says when a folder was too big to list in full', async () => {
    open();
    await answer({ ...HOME, truncated: true }, null);

    expect(rendered().textContent).toContain('Only the first 5000 are listed.');
  });

  it('chooses the folder on screen', async () => {
    open({ start: '/home/deploy/app' });
    await answer(APP, '/home/deploy/app');

    buttonNamed('Choose this folder')?.click();

    expect(close).toHaveBeenCalledWith('/home/deploy/app');
  });

  it('offers the projects found as quick picks', async () => {
    open({ projects: ['/srv/blog'] });
    await answer(HOME, null);

    buttonNamed('/srv/blog')?.click();
    await answer(folderOf('/srv/blog', [], true), '/srv/blog');

    expect(browser.path()).toBe('/srv/blog');
  });

  it('picks a file in file mode and has no folder choice', async () => {
    open({ mode: 'file', start: '/home/deploy/app' });
    await answer(APP, '/home/deploy/app');

    expect(buttonNamed('Choose this folder')).toBeUndefined();
    const envButton = rendered().querySelector<HTMLButtonElement>('button[aria-label="Choose .env"]');
    envButton?.click();

    expect(close).toHaveBeenCalledWith('/home/deploy/app/.env');
  });

  it('says why a folder could not be read and goes home from there', async () => {
    open({ start: '/var/backups/dbs' });
    TestBed.tick();
    http
      .expectOne((each) => each.url === BROWSE)
      .flush({ error: { code: 'remote_not_found', message: 'prose' } }, { status: 404, statusText: 'Not Found' });
    await settle();

    expect(rendered().textContent).toContain('The folder or file does not exist on the server.');

    buttonNamed('Home')?.click();
    await answer(HOME, null);
    expect(browser.path()).toBe('/home/deploy');
  });
});
