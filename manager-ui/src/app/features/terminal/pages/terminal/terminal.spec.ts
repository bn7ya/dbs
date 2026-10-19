import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, type TestRequest } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, type Routes } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { of } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';

import { MASTER } from '@core/auth/testing/identity.fixtures';
import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import { Dialogs } from '@shared/dialogs/dialogs';
import type { DialogHandle } from '@shared/dialogs/dialogs.types';
import { PasswordPrompt } from '@shared/password-prompt/password-prompt';
import type { PasswordPromptData } from '@shared/password-prompt/password-prompt.types';
import { TERMINAL_SCREENS } from '@shared/terminal-view/terminal-screens';
import { FakeTerminalScreens } from '@shared/terminal-view/testing/fake-terminal-screens';
import type { Terminal } from '../../data/terminals.types';
import {
  APPLICATION,
  APPLICATION_ID,
  SERVER,
  SERVER_ID,
  TERMINAL,
  outputOf,
} from '../../testing/terminal.fixtures';
import { TerminalPage } from './terminal';

const ROUTES: Routes = [
  {
    path: 'servers/:serverId',
    children: [
      {
        path: 'terminal',
        data: { mode: 'server' },
        loadChildren: () => import('../../terminal.routes').then((m) => m.routes),
      },
    ],
  },
  {
    path: 'applications/:applicationId',
    children: [
      {
        path: 'terminal',
        data: { mode: 'application' },
        loadChildren: () => import('../../terminal.routes').then((m) => m.routes),
      },
    ],
  },
  { path: 'elsewhere', children: [] },
];

describe('TerminalPage', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;
  let screens: FakeTerminalScreens;

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const listRequest = (): TestRequest =>
    http.expectOne((request) => request.url === '/api/terminals/' && request.method === 'GET');
  const openRequest = (): TestRequest =>
    http.expectOne((request) => request.url === '/api/terminals/' && request.method === 'POST');
  const outputRequest = (cursor: number, id = TERMINAL.id): TestRequest =>
    http.expectOne(`/api/terminals/${id}/output/?cursor=${cursor}`);

  const show = async (url: string, open: readonly Terminal[] = []): Promise<void> => {
    harness = await RouterTestingHarness.create();
    const navigating = harness.navigateByUrl(url, TerminalPage);
    (await vi.waitFor(() => http.expectOne('/api/auth/me/'))).flush(MASTER);
    await navigating;
    TestBed.tick();
    if (url.startsWith('/servers/')) {
      http.expectOne(`/api/servers/${SERVER_ID}/`).flush(SERVER);
    } else {
      http.expectOne(`/api/applications/${APPLICATION_ID}/`).flush(APPLICATION);
    }
    listRequest().flush({ results: open });
    await settle();
    harness.detectChanges();
  };

  const showServer = (open: readonly Terminal[] = []): Promise<void> => show(`/servers/${SERVER_ID}/terminal`, open);

  const element = (): HTMLElement => harness.routeNativeElement as HTMLElement;
  const textOf = (): string => element().textContent?.replace(/\s+/g, ' ').trim() ?? '';
  const buttonNamed = (text: string): HTMLButtonElement | undefined =>
    Array.from(element().querySelectorAll('button')).find((button) => button.textContent?.trim() === text);
  const refresh = async (): Promise<void> => {
    await settle();
    harness.detectChanges();
  };

  let closeDialog: (result: boolean) => void;

  const stubDialog = (): MockInstance<Dialogs['open']> => {
    const closing = new Promise<boolean>((resolve) => (closeDialog = resolve));
    const handle: DialogHandle<unknown> = { closed: of(true), whenClosed: () => closing };
    const page = harness.routeDebugElement;
    if (page === null) {
      throw new Error('The page is not on screen.');
    }
    return vi.spyOn(page.injector.get(Dialogs), 'open').mockReturnValue(handle);
  };

  const promptData = (open: MockInstance<Dialogs['open']>): PasswordPromptData => {
    const [component, options] = open.mock.calls[0];
    expect(component).toBe(PasswordPrompt);
    return options.data as PasswordPromptData;
  };

  const openTerminal = async (): Promise<PasswordPromptData> => {
    const open = stubDialog();
    buttonNamed('Open a terminal')?.click();
    await vi.waitFor(() => expect(open).toHaveBeenCalledOnce());
    const data = promptData(open);
    const submitting = data.submit('hunter2');
    openRequest().flush(TERMINAL, { status: 201, statusText: 'Created' });
    await expect(submitting).resolves.toBe(true);
    closeDialog(true);
    await refresh();
    return data;
  };

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    screens = new FakeTerminalScreens();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter(ROUTES),
        { provide: TERMINAL_SCREENS, useValue: screens },
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    try {
      http.verify({ ignoreCancelled: true });
    } finally {
      TestBed.resetTestingModule();
      localStorage.clear();
      vi.restoreAllMocks();
    }
  });

  it('says where the shell runs and what is kept of it, under a second-level title', async () => {
    await showServer();

    expect(element().querySelector('h1')).toBeNull();
    expect(element().querySelector('h2')?.textContent?.trim()).toBe('Terminal');
    expect(textOf()).toContain('A login shell on ⁨web-1⁩, as ⁨deploy⁩, the SSH user the manager signs in with.');
    expect(textOf()).toContain('What you type and what the shell shows are never recorded.');
    expect(textOf()).toContain('It closes after 15 minutes without typing');
    expect(buttonNamed('Open a terminal')?.disabled).toBe(false);
    expect(buttonNamed('Close the terminal')).toBeUndefined();
    expect(screens.screen.options.disableStdin).toBe(true);
    expect(element().querySelector('[role="group"]')?.getAttribute('aria-label')).toBe('Shell for ⁨web-1⁩');
  });

  it("says which Compose service an application's shell opens in, in Arabic too", async () => {
    await show(`/applications/${APPLICATION_ID}/terminal`);

    expect(textOf()).toContain('A shell inside ⁨web⁩, the Compose service that runs ⁨shop⁩.');
    TestBed.inject(LocaleStore).setLocale('ar');
    harness.detectChanges();
    expect(element().querySelector('h2')?.textContent?.trim()).toBe('الطرفية');
    expect(textOf()).toContain('صدفة داخل ⁨web⁩، خدمة Compose التي تشغل ⁨shop⁩.');
  });

  it('says when it cannot read where the shell would run, and tries again', async () => {
    harness = await RouterTestingHarness.create();
    const navigating = harness.navigateByUrl(`/servers/${SERVER_ID}/terminal`, TerminalPage);
    (await vi.waitFor(() => http.expectOne('/api/auth/me/'))).flush(MASTER);
    await navigating;
    TestBed.tick();
    http
      .expectOne(`/api/servers/${SERVER_ID}/`)
      .flush({ error: { code: 'not_found', message: 'Not found.' } }, { status: 404, statusText: 'Not Found' });
    listRequest().flush({ results: [] });
    await refresh();

    expect(textOf()).toContain('This no longer exists.');
    buttonNamed('Try again')?.click();
    TestBed.tick();
    http.expectOne(`/api/servers/${SERVER_ID}/`).flush(SERVER);
    await refresh();

    expect(textOf()).not.toContain('This no longer exists.');
    expect(textOf()).toContain('A login shell on ⁨web-1⁩');
  });

  it('asks for the password, opens the shell at the size of the view and shows what it prints', async () => {
    await showServer();
    screens.fitter.fitsTo = { cols: 120, rows: 40 };
    screens.fitter.fit();

    const data = await openTerminal();

    expect(data.titleKey).toBe('terminal.prompt.title');
    expect(data.bodyValues).toEqual({ name: '⁨web-1⁩' });
    expect(screens.screen.resets).toBe(1);
    expect(screens.screen.focuses).toBe(1);
    expect(screens.screen.options.disableStdin).toBe(false);
    expect(textOf()).toContain('Terminal open');
    expect(buttonNamed('Close the terminal')).toBeDefined();
    expect(buttonNamed('Open a terminal')).toBeUndefined();

    outputRequest(0).flush(outputOf('deploy@web-1:~$ ', 16));
    expect(screens.screen.text()).toBe('deploy@web-1:~$ ');
    outputRequest(16);
  });

  it('sends what is typed in the terminal', async () => {
    await showServer();
    await openTerminal();
    outputRequest(0);

    screens.screen.type('ls\r');

    const input = await vi.waitFor(() => http.expectOne(`/api/terminals/${TERMINAL.id}/input/`));
    expect((input.request.body as { data: string }).data).toBe('ls\r');
    input.flush({ accepted: true });
  });

  it('keeps the prompt open on a wrong password', async () => {
    await showServer();
    const open = stubDialog();
    buttonNamed('Open a terminal')?.click();
    await vi.waitFor(() => expect(open).toHaveBeenCalledOnce());
    const data = promptData(open);

    const submitting = data.submit('wrong');
    openRequest().flush(
      { error: { code: 'invalid_password', message: 'That password is not right.' } },
      { status: 400, statusText: 'Bad Request' },
    );

    await expect(submitting).resolves.toBe(false);
    expect(data.error()?.code).toBe('invalid_password');
  });

  it('says why a terminal would not open', async () => {
    await showServer();
    const open = stubDialog();
    buttonNamed('Open a terminal')?.click();
    await vi.waitFor(() => expect(open).toHaveBeenCalledOnce());

    const submitting = promptData(open).submit('hunter2');
    openRequest().flush(
      { error: { code: 'terminal_off', message: 'The terminal is switched off for this manager.' } },
      { status: 403, statusText: 'Forbidden' },
    );
    await expect(submitting).resolves.toBe(true);
    closeDialog(true);
    await refresh();

    const notice = element().querySelector('app-notice[role="alert"]');
    expect(notice?.textContent).toContain('The terminal is switched off for this manager.');

    notice?.querySelector('button')?.click();
    await refresh();
    expect(element().querySelector('app-notice[role="alert"]')).toBeNull();
  });

  it('says why the terminal closed and offers to open another', async () => {
    await showServer();
    await openTerminal();

    outputRequest(0).flush(outputOf('', 0, { closed: true, reason: 'idle' }));
    TestBed.tick();
    listRequest().flush({ results: [] });
    await refresh();

    expect(textOf()).toContain('The terminal closed after 15 minutes without typing.');
    expect(buttonNamed('Open a terminal')).toBeDefined();
    expect(screens.screen.options.disableStdin).toBe(true);
  });

  it('gives the status a shell exited with', async () => {
    await showServer();
    await openTerminal();

    outputRequest(0).flush(outputOf('', 0, { closed: true, reason: 'exited', exit_status: 130 }));
    TestBed.tick();
    listRequest().flush({ results: [] });
    await refresh();

    expect(textOf()).toContain('The shell exited with status 130.');
  });

  it('closes the terminal with the Close button', async () => {
    await showServer();
    await openTerminal();
    const reading = outputRequest(0);

    buttonNamed('Close the terminal')?.click();
    http
      .expectOne((request) => request.method === 'DELETE' && request.url === `/api/terminals/${TERMINAL.id}/`)
      .flush(null, { status: 204, statusText: 'No Content' });
    TestBed.tick();
    listRequest().flush({ results: [] });
    await refresh();

    expect(reading.cancelled).toBe(true);
    expect(textOf()).toContain('You closed the terminal.');
  });

  it('offers to reattach a terminal still open here, and reattaches without a password', async () => {
    await showServer([TERMINAL]);
    const open = stubDialog();

    expect(textOf()).toContain('A terminal you opened here is still running.');
    buttonNamed('Reattach')?.click();
    await refresh();

    expect(open).not.toHaveBeenCalled();
    expect(textOf()).toContain('Reattached. Earlier output is not shown');
    expect(textOf()).not.toContain('A terminal you opened here is still running.');
    expect(screens.screen.focuses).toBe(1);
    outputRequest(0).flush(outputOf('$ ', 300, { skipped: true }));
    expect(screens.screen.text()).toBe('$ ');
    outputRequest(300);
  });

  it('closes a terminal still open here when asked', async () => {
    await showServer([TERMINAL]);

    buttonNamed('Close it')?.click();
    http
      .expectOne((request) => request.method === 'DELETE' && request.url === `/api/terminals/${TERMINAL.id}/`)
      .flush(null, { status: 204, statusText: 'No Content' });
    TestBed.tick();
    listRequest().flush({ results: [] });
    await refresh();

    expect(textOf()).not.toContain('A terminal you opened here is still running.');
  });

  it('closes the terminal when the page is left', async () => {
    await showServer();
    await openTerminal();
    const reading = outputRequest(0);

    await harness.navigateByUrl('/elsewhere');

    http
      .expectOne((request) => request.method === 'DELETE' && request.url === `/api/terminals/${TERMINAL.id}/`)
      .flush(null, { status: 204, statusText: 'No Content' });
    expect(reading.cancelled).toBe(true);
  });
});
