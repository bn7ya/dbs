import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { provideRouter } from '@angular/router';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import type { Server } from '../../data/servers.types';
import { ServersStore } from '../../state/servers.store';
import { SERVER } from '../../testing/servers.fixtures';
import { ServerForm } from './server-form';
import type { ServerFormData } from './server-form.types';

const DETAIL = `/api/servers/${SERVER.id}/`;

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
        { provide: MatDialogRef, useValue: { close } },
        { provide: MAT_DIALOG_DATA, useValue: { data } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    return TestBed.createComponent(ServerForm).componentInstance;
  };

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
  });

  it('sends only what changed and keeps the saved key when its field is left empty', async () => {
    const form = open({ server: SERVER });
    form.update('name', 'Production web 2');

    const saving = form.save();
    const request = http.expectOne(DETAIL);
    expect(request.request.method).toBe('PATCH');
    expect(request.request.body).toEqual({ name: 'Production web 2' });
    request.flush({ ...SERVER, name: 'Production web 2' });
    await saving;

    expect(close).toHaveBeenCalledWith({ ...SERVER, name: 'Production web 2' });
  });

  it('closes without a request when nothing changed', async () => {
    const form = open({ server: SERVER });

    await form.save();

    expect(close).toHaveBeenCalledWith();
  });

  it('asks for the account password only when the backend wants it, then sends it', async () => {
    const form = open({ server: SERVER });
    form.update('host', 'web-2.example.com');

    const first = form.save();
    const refused = http.expectOne(DETAIL);
    expect(refused.request.body).toEqual({ host: 'web-2.example.com' });
    refused.flush(
      { error: { code: 'invalid', message: 'Server prose', fields: { account_password: ['required'] } } },
      { status: 400, statusText: 'Bad Request' },
    );
    await first;
    expect(form.passwordShown()).toBe(true);
    expect(form.passwordMissing()).toBe(true);
    expect(close).not.toHaveBeenCalled();

    await form.save();
    http.expectNone(DETAIL);

    form.setAccountPassword('hunter2');
    const second = form.save();
    const sent = http.expectOne(DETAIL);
    expect(sent.request.body).toEqual({ host: 'web-2.example.com', account_password: 'hunter2' });
    sent.flush({ ...SERVER, host: 'web-2.example.com' });
    await second;

    expect(close).toHaveBeenCalled();
  });

  it('puts a backend field error under its field and drops it once edited', async () => {
    const form = open({ server: SERVER });
    form.update('name', 'Staging');

    const saving = form.save();
    http.expectOne(DETAIL).flush(
      { error: { code: 'invalid', message: 'Server prose', fields: { name: ['name_taken'] } } },
      { status: 400, statusText: 'Bad Request' },
    );
    await saving;

    expect(form.error('name')).toBe('name_taken');
    form.update('name', 'Staging 2');
    expect(form.error('name')).toBeNull();
  });

  it('wants a password when a key server switches to one, and sends the method with it', async () => {
    const form = open({ server: SERVER });
    form.setAuthMethod('password');

    await form.save();
    http.expectNone(DETAIL);
    expect(form.error('password')).toBe('required');

    form.update('password', 's3cret');
    const saving = form.save();
    const request = http.expectOne(DETAIL);
    expect(request.request.body).toEqual({ auth_method: 'password', password: 's3cret' });
    const saved: Server = { ...SERVER, auth_method: 'password', has_password: true, has_private_key: false };
    request.flush(saved);
    await saving;

    expect(close).toHaveBeenCalledWith(saved);
  });
});
