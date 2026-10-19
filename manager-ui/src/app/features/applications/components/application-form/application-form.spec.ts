import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { provideRouter } from '@angular/router';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { Dialogs } from '@shared/dialogs/dialogs';
import type { DialogOptions } from '@shared/dialogs/dialogs.types';
import { ApplicationsStore } from '../../state/applications.store';
import { APPLICATION, SERVER_ID } from '../../testing/applications.fixtures';
import type { ServerBrowserData } from '../server-browser/server-browser.types';
import { ApplicationForm } from './application-form';

const DETAIL = `/api/applications/${APPLICATION.id}/`;

describe('ApplicationForm', () => {
  let http: HttpTestingController;
  let close: ReturnType<typeof vi.fn>;
  let browsed: ReturnType<typeof vi.fn>;
  let picked: string | undefined;

  const open = async (): Promise<ApplicationForm> => {
    close = vi.fn();
    picked = undefined;
    browsed = vi.fn(() => ({ whenClosed: () => Promise.resolve(picked) }));
    TestBed.configureTestingModule({
      providers: [
        ApplicationsStore,
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: MatDialogRef, useValue: { close } },
        { provide: MAT_DIALOG_DATA, useValue: { data: { application: APPLICATION } } },
        { provide: Dialogs, useValue: { open: browsed } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    const store = TestBed.inject(ApplicationsStore);
    store.select(APPLICATION.id);
    TestBed.tick();
    http.expectOne(DETAIL).flush(APPLICATION);
    await TestBed.inject(ApplicationRef).whenStable();
    return TestBed.createComponent(ApplicationForm).componentInstance;
  };

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
  });

  it('sends only what changed', async () => {
    const form = await open();
    form.update('settings_module', 'shop.settings.prod');

    const saving = form.save();
    const request = http.expectOne(DETAIL);
    expect(request.request.method).toBe('PATCH');
    expect(request.request.body).toEqual({ settings_module: 'shop.settings.prod' });
    request.flush({ ...APPLICATION, settings_module: 'shop.settings.prod' });
    await saving;

    expect(close).toHaveBeenCalledWith({ ...APPLICATION, settings_module: 'shop.settings.prod' });
  });

  it('holds a value that cannot be saved under its field', async () => {
    const form = await open();
    form.update('project_dir', 'srv/shop');

    await form.save();

    http.expectNone(DETAIL);
    expect(form.errors().project_dir).toBe('absolute_path_required');
  });

  it('asks for the account password when the backend wants it, then sends it', async () => {
    const form = await open();
    form.update('python_path', 'python3');

    const first = form.save();
    http.expectOne(DETAIL).flush(
      { error: { code: 'invalid', message: 'Server prose', fields: { account_password: ['required'] } } },
      { status: 400, statusText: 'Bad Request' },
    );
    await first;
    expect(form.passwordShown()).toBe(true);
    expect(close).not.toHaveBeenCalled();

    form.setAccountPassword('hunter2');
    const second = form.save();
    const sent = http.expectOne(DETAIL);
    expect(sent.request.body).toEqual({ python_path: 'python3', account_password: 'hunter2' });
    sent.flush({ ...APPLICATION, python_path: 'python3' });
    await second;

    expect(close).toHaveBeenCalled();
  });

  it('browses the application’s server for a path and adds a folder to allow', async () => {
    const form = await open();

    picked = '/srv/shop/media';
    await form.browse('file_roots');
    const [, options] = browsed.mock.calls[0] as [unknown, DialogOptions<ServerBrowserData>];
    expect(options.data).toMatchObject({ serverId: SERVER_ID, mode: 'folder' });
    expect(form.draft().file_roots).toEqual(['/app/media', '/srv/shop/media']);

    picked = '/srv/shop/.env.prod';
    await form.browse('env_path');
    expect(form.draft().env_path).toBe('/srv/shop/.env.prod');
  });
});
