import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { DynamicDialogConfig, DynamicDialogRef } from 'primeng/dynamicdialog';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import type { Server } from '../../data/servers.types';
import { ServersStore } from '../../state/servers.store';
import { SERVER } from '../../testing/servers.fixtures';
import { ServerForm } from './server-form';
import type { ServerFormData } from './server-form.types';

const HOST_KEY = { key_type: 'ssh-ed25519', line: 'web-1 ssh-ed25519 AAAA', fingerprint: 'SHA256:abc' };

describe('ServerForm', () => {
  let http: HttpTestingController;
  let close: ReturnType<typeof vi.fn>;

  const open = (data: ServerFormData): ServerForm => {
    close = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        ServersStore,
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: DynamicDialogRef, useValue: { close } },
        { provide: DynamicDialogConfig, useValue: { data } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    return TestBed.createComponent(ServerForm).componentInstance;
  };

  const fillConnection = (form: ServerForm): void => {
    form.update('name', 'Production web');
    form.update('host', 'web-1.example.com');
    form.update('username', 'deploy');
    form.update('private_key', '-----BEGIN OPENSSH PRIVATE KEY-----');
  };

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
  });

  it('holds the reader on a step until its fields are filled, and says why', async () => {
    const form = open({ server: null });
    expect(form.error('name')).toBeNull();

    await form.advance();

    expect(form.step()).toBe(0);
    expect(form.error('name')).toBe('required');
    expect(form.error('private_key')).toBe('required');
  });

  it('marks a step done only once the reader has moved past it', async () => {
    const form = open({ server: null });
    expect([form.stepDone('connection'), form.stepDone('hostKey'), form.stepDone('project')]).toEqual([
      false,
      false,
      false,
    ]);
    expect(form.stepReady('project')).toBe(true);

    fillConnection(form);
    await form.advance();

    expect([form.stepDone('connection'), form.stepDone('hostKey'), form.stepDone('project')]).toEqual([
      true,
      false,
      false,
    ]);
  });

  it('needs the host key fetched and compared before the last step', async () => {
    const form = open({ server: null });
    fillConnection(form);
    await form.advance();
    expect(form.step()).toBe(1);

    await form.advance();
    expect(form.step()).toBe(1);
    expect(form.error('host_key')).toBe('host_key_missing');

    const fetching = form.fetchHostKey();
    const request = http.expectOne('/api/servers/fingerprint/');
    expect(request.request.body).toEqual({ host: 'web-1.example.com', port: 22 });
    request.flush(HOST_KEY);
    await fetching;

    await form.advance();
    expect(form.error('host_key')).toBe('host_key_unconfirmed');

    form.hostKeyConfirmed.set(true);
    await form.advance();
    expect(form.step()).toBe(2);
  });

  it('forgets a fetched key when the address changes', async () => {
    const form = open({ server: null });
    fillConnection(form);
    const fetching = form.fetchHostKey();
    http.expectOne('/api/servers/fingerprint/').flush(HOST_KEY);
    await fetching;
    form.hostKeyConfirmed.set(true);

    form.update('port', 2222);

    expect(form.hostKey()).toBeNull();
    expect(form.hostKeyConfirmed()).toBe(false);
  });

  it('sends the pinned key line and only the secrets of the chosen method, then closes', async () => {
    const form = open({ server: null });
    fillConnection(form);
    form.update('password', 'typed before switching to a key');
    const fetching = form.fetchHostKey();
    http.expectOne('/api/servers/fingerprint/').flush(HOST_KEY);
    await fetching;
    form.hostKeyConfirmed.set(true);
    form.step.set(2);

    const saving = form.advance();
    const request = http.expectOne('/api/servers/');
    expect(request.request.body).toMatchObject({
      name: 'Production web',
      host_key: HOST_KEY.line,
      private_key: '-----BEGIN OPENSSH PRIVATE KEY-----',
    });
    expect(request.request.body).not.toHaveProperty('password');
    expect(request.request.body).not.toHaveProperty('backup_passphrase');
    request.flush(SERVER, { status: 201, statusText: 'Created' });
    await saving;

    expect(close).toHaveBeenCalledWith(SERVER);
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
});
