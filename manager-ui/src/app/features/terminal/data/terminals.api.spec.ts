import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { APPLICATION, APPLICATION_ID, SERVER, SERVER_ID, TERMINAL, outputOf } from '../testing/terminal.fixtures';
import { TerminalsApi } from './terminals.api';

describe('TerminalsApi', () => {
  let api: TerminalsApi;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(TerminalsApi);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
  });

  it("lists this session's open terminals", async () => {
    const listing = firstValueFrom(api.list());
    const request = http.expectOne('/api/terminals/');
    expect(request.request.method).toBe('GET');
    request.flush({ results: [TERMINAL] });

    await expect(listing).resolves.toEqual([TERMINAL]);
  });

  it('opens a terminal with the place, the password and the size', async () => {
    const opening = firstValueFrom(
      api.open({ mode: 'server', server: SERVER_ID, password: 'hunter2', cols: 120, rows: 40 }),
    );
    const request = http.expectOne('/api/terminals/');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ mode: 'server', server: SERVER_ID, password: 'hunter2', cols: 120, rows: 40 });
    request.flush(TERMINAL, { status: 201, statusText: 'Created' });

    await expect(opening).resolves.toEqual(TERMINAL);
  });

  it('reads output from a cursor and decodes it to bytes, whatever the characters', async () => {
    const reading = firstValueFrom(api.output(TERMINAL.id, 42));
    const request = http.expectOne(`/api/terminals/${TERMINAL.id}/output/?cursor=42`);
    expect(request.request.method).toBe('GET');
    request.flush(outputOf('ls\r\nمرحبا\r\n', 60));

    const output = await reading;
    expect(new TextDecoder().decode(output.bytes)).toBe('ls\r\nمرحبا\r\n');
    expect(output).toMatchObject({ cursor: 60, skipped: false, closed: false, reason: null, exitStatus: null });
  });

  it('says why a terminal closed and how its shell exited', async () => {
    const reading = firstValueFrom(api.output(TERMINAL.id, 60));
    http
      .expectOne(`/api/terminals/${TERMINAL.id}/output/?cursor=60`)
      .flush(outputOf('', 60, { closed: true, reason: 'exited', exit_status: 3, skipped: true }));

    const output = await reading;
    expect(output.bytes).toHaveLength(0);
    expect(output).toMatchObject({ skipped: true, closed: true, reason: 'exited', exitStatus: 3 });
  });

  it('sends keystrokes with their sequence number', async () => {
    const sending = firstValueFrom(api.input(TERMINAL.id, 7, 'ls\r'));
    const request = http.expectOne(`/api/terminals/${TERMINAL.id}/input/`);
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ seq: 7, data: 'ls\r' });
    request.flush({ accepted: true });

    await expect(sending).resolves.toEqual({ accepted: true });
  });

  it('resizes and closes a terminal', async () => {
    const resizing = firstValueFrom(api.resize(TERMINAL.id, { cols: 100, rows: 30 }));
    const resize = http.expectOne(`/api/terminals/${TERMINAL.id}/resize/`);
    expect(resize.request.method).toBe('POST');
    expect(resize.request.body).toEqual({ cols: 100, rows: 30 });
    resize.flush({ ...TERMINAL, cols: 100, rows: 30 });
    await expect(resizing).resolves.toMatchObject({ cols: 100, rows: 30 });

    const closing = firstValueFrom(api.close(TERMINAL.id), { defaultValue: undefined });
    const close = http.expectOne(`/api/terminals/${TERMINAL.id}/`);
    expect(close.request.method).toBe('DELETE');
    close.flush(null, { status: 204, statusText: 'No Content' });
    await expect(closing).resolves.toBeNull();
  });

  it('reads the server or the application a terminal opens on', async () => {
    const server = firstValueFrom(api.server(SERVER_ID));
    http.expectOne(`/api/servers/${SERVER_ID}/`).flush(SERVER);
    await expect(server).resolves.toEqual(SERVER);

    const application = firstValueFrom(api.application(APPLICATION_ID));
    http.expectOne(`/api/applications/${APPLICATION_ID}/`).flush(APPLICATION);
    await expect(application).resolves.toEqual(APPLICATION);
  });
});
