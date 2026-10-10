import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { TestBed } from '@angular/core/testing';
import { MatStepperHarness } from '@angular/material/stepper/testing';
import { provideRouter } from '@angular/router';
import type { MatChipInputEvent } from '@angular/material/chips';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import { Dialogs } from '@shared/dialogs/dialogs';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import type { Server } from '../../data/servers.types';
import { ServersStore } from '../../state/servers.store';
import { SERVER } from '../../testing/servers.fixtures';
import { ServerForm } from './server-form';
import type { ServerFormData } from './server-form.types';

describe('ServerForm', () => {
  let http: HttpTestingController;
  let close: ReturnType<typeof vi.fn>;
  let browsed: ReturnType<typeof vi.fn>;
  let chosen: string | undefined;

  const open = (data: ServerFormData): ServerForm => {
    close = vi.fn();
    chosen = undefined;
    browsed = vi.fn(() => ({ whenClosed: () => Promise.resolve(chosen) }));
    TestBed.configureTestingModule({
      providers: [
        ServersStore,
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: MatDialogRef, useValue: { close } },
        { provide: MAT_DIALOG_DATA, useValue: { data } },
        { provide: Dialogs, useValue: { open: browsed } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    return TestBed.createComponent(ServerForm).componentInstance;
  };

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
  });

  it('puts a backend field error under its field, opens its step, and drops it once edited', async () => {
    const form = open({ server: SERVER });
    form.step.set(1);

    const saving = form.advance();
    http.expectOne(`/api/servers/${SERVER.id}/`).flush(
      { error: { code: 'invalid', message: 'Server prose', fields: { name: ['name_taken'] } } },
      { status: 400, statusText: 'Bad Request' },
    );
    await saving;

    expect(close).not.toHaveBeenCalled();
    expect(form.step()).toBe(0);
    expect(form.error('name')).toBe('name_taken');

    form.update('name', 'Production web 2');
    expect(form.error('name')).toBeNull();
  });

  it('keeps a saved secret when its field is left empty on an edit', async () => {
    const edited: Server = { ...SERVER, has_private_key: true };
    const form = open({ server: edited });
    form.step.set(1);

    const saving = form.advance();
    const request = http.expectOne(`/api/servers/${SERVER.id}/`);
    expect(request.request.method).toBe('PATCH');
    expect(request.request.body).not.toHaveProperty('private_key');
    expect(request.request.body).not.toHaveProperty('host_key');
    expect(request.request.body).not.toHaveProperty('account_password');
    request.flush(edited);
    await saving;

    expect(close).toHaveBeenCalledWith(edited);
  });

  it('asks for the reader\'s password once an edit changes more than the name, and sends it', async () => {
    const form = open({ server: SERVER });
    form.update('name', 'Production web 2');
    expect(form.passwordShown()).toBe(false);

    form.update('env_path', '/srv/other/.env');
    expect(form.passwordShown()).toBe(true);
    form.step.set(1);
    await form.advance();
    expect(form.passwordMissing()).toBe(true);

    form.setAccountPassword('correct-horse-battery-staple');
    const saving = form.advance();
    const request = http.expectOne(`/api/servers/${SERVER.id}/`);
    expect(request.request.body).toMatchObject({
      env_path: '/srv/other/.env',
      account_password: 'correct-horse-battery-staple',
    });
    request.flush({ ...SERVER, env_path: '/srv/other/.env' });
    await saving;

    expect(close).toHaveBeenCalled();
  });

  it('asks for a password to replace a secret, and says a wrong one under its field', async () => {
    const form = open({ server: SERVER });
    form.update('private_key', '-----BEGIN OPENSSH PRIVATE KEY-----');
    expect(form.passwordShown()).toBe(true);
    form.setAccountPassword('wrong');
    form.step.set(1);

    const saving = form.advance();
    http.expectOne(`/api/servers/${SERVER.id}/`).flush(
      { error: { code: 'invalid_password', message: 'Server prose' } },
      { status: 400, statusText: 'Bad Request' },
    );
    await saving;

    expect(close).not.toHaveBeenCalled();
    expect(form.passwordRejected()).toBe(true);
    expect(form.formFailure()).toBeNull();
    form.setAccountPassword('correct-horse-battery-staple');
    expect(form.passwordRejected()).toBe(false);
  });

  it('shows the password field when the backend asks for one the form did not expect', async () => {
    const form = open({ server: SERVER });
    form.step.set(1);

    const saving = form.advance();
    http.expectOne(`/api/servers/${SERVER.id}/`).flush(
      { error: { code: 'invalid', message: 'Server prose', fields: { account_password: ['required'] } } },
      { status: 400, statusText: 'Bad Request' },
    );
    await saving;

    expect(form.passwordShown()).toBe(true);
    expect(form.passwordMissing()).toBe(true);
    expect(form.step()).toBe(1);
  });

  it('adds an allowed folder from what was typed, and removes the one asked for', () => {
    const form = open({ server: SERVER });
    const clear = vi.fn();
    const typed = (value: string): MatChipInputEvent =>
      ({ value, chipInput: { clear } }) as unknown as MatChipInputEvent;

    form.addFileRoot(typed(' /srv/app/media '));
    form.addFileRoot(typed('   '));
    form.addFileRoot(typed('/srv/app/uploads'));

    expect(form.draft().file_roots).toEqual([...SERVER.file_roots, '/srv/app/media', '/srv/app/uploads']);
    expect(clear).toHaveBeenCalledTimes(3);

    form.removeFileRoot(SERVER.file_roots.length);
    expect(form.draft().file_roots).toEqual([...SERVER.file_roots, '/srv/app/uploads']);
  });

  it('fills a path, or adds an allowed folder, from the folder chosen on the server', async () => {
    const form = open({ server: SERVER });

    chosen = '/srv/app/uploads';
    await form.browse('file_roots');
    await form.browse('file_roots');
    expect(form.draft().file_roots).toEqual([...SERVER.file_roots, '/srv/app/uploads']);
    expect(browsed.mock.calls[0][1]).toMatchObject({
      titleKey: 'servers.browser.title.folder',
      data: { serverId: SERVER.id, start: SERVER.project_dir, mode: 'folder' },
    });

    chosen = '/etc/app.env';
    await form.browse('env_path');
    expect(form.draft().env_path).toBe('/etc/app.env');
    expect(browsed.mock.calls[2][1]).toMatchObject({ data: { mode: 'file' } });

    chosen = undefined;
    await form.browse('project_dir');
    expect(form.draft().project_dir).toBe(SERVER.project_dir);
  });

  it('edits a server in two steps, either of which opens at once', async () => {
    localStorage.setItem('locale', 'en');
    open({ server: SERVER });
    TestBed.inject(LocaleStore).register({ en, ar });
    const fixture = TestBed.createComponent(ServerForm);
    fixture.detectChanges();
    const stepper = await TestbedHarnessEnvironment.loader(fixture).getHarness(MatStepperHarness);
    const steps = await stepper.getSteps();

    expect(await Promise.all(steps.map((step) => step.getLabel()))).toEqual(['Connection', 'django-dbs and files']);

    await steps[1].select();
    expect(await steps[1].isSelected()).toBe(true);
    expect(fixture.componentInstance.step()).toBe(1);
    localStorage.clear();
  });
});
