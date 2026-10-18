import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, type TestRequest } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, type Routes } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { of } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';

import { OPERATOR } from '@core/auth/testing/identity.fixtures';
import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import { Dialogs } from '@shared/dialogs/dialogs';
import type { DialogHandle } from '@shared/dialogs/dialogs.types';
import { PasswordPrompt } from '@shared/password-prompt/password-prompt';
import type { PasswordPromptData } from '@shared/password-prompt/password-prompt.types';
import type { ConsoleResult } from '../../data/console.types';
import {
  ACTIVITY_ID,
  HELP,
  LISTED,
  NEEDS_PASSWORD,
  REFUSED_ROLE,
  RUNNING_JOB,
  STARTED,
} from '../../testing/console.fixtures';
import { ConsolePage } from './console';

const ROUTES: Routes = [
  { path: 'console', loadChildren: () => import('../../console.routes').then((m) => m.routes) },
  { path: 'activity', children: [] },
];

describe('ConsolePage', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;

  const settle = async (): Promise<void> => {
    await TestBed.inject(ApplicationRef).whenStable();
    harness.detectChanges();
  };

  const show = async (): Promise<void> => {
    harness = await RouterTestingHarness.create();
    const navigating = harness.navigateByUrl('/console', ConsolePage);
    (await vi.waitFor(() => http.expectOne('/api/auth/me/'))).flush(OPERATOR);
    await navigating;
    await settle();
  };

  const element = (): HTMLElement => harness.routeNativeElement as HTMLElement;
  const log = (): HTMLElement => {
    const found = element().querySelector<HTMLElement>('[role="log"]');
    if (found === null) {
      throw new Error('The log is not on screen.');
    }
    return found;
  };
  const field = (): HTMLInputElement => {
    const found = element().querySelector<HTMLInputElement>('input[name="line"]');
    if (found === null) {
      throw new Error('The command field is not on screen.');
    }
    return found;
  };
  const textOf = (node: Element): string => node.textContent?.replace(/\s+/g, ' ').trim() ?? '';
  const entries = (): HTMLElement[] => Array.from(log().querySelectorAll<HTMLElement>('.console__entry'));
  const buttonNamed = (text: string): HTMLButtonElement | undefined =>
    Array.from(element().querySelectorAll('button')).find((button) => button.textContent?.trim() === text);
  const consoleRequest = (): TestRequest => http.expectOne('/api/console/');

  const type = async (line: string): Promise<void> => {
    field().value = line;
    field().dispatchEvent(new Event('input'));
    await settle();
  };

  const run = async (line: string, answer: ConsoleResult): Promise<TestRequest> => {
    await type(line);
    buttonNamed('Run')?.click();
    const request = consoleRequest();
    request.flush(answer);
    await settle();
    return request;
  };

  const press = async (key: string): Promise<void> => {
    field().dispatchEvent(new KeyboardEvent('keydown', { key, cancelable: true }));
    await settle();
  };

  const stubDialog = (result: boolean | undefined = true): MockInstance<Dialogs['open']> => {
    const handle: DialogHandle<unknown> = { closed: of(result), whenClosed: () => Promise.resolve(result) };
    const page = harness.routeDebugElement;
    if (page === null) {
      throw new Error('The page is not on screen.');
    }
    return vi.spyOn(page.injector.get(Dialogs), 'open').mockReturnValue(handle);
  };

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter(ROUTES),
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    try {
      http.verify();
    } finally {
      TestBed.resetTestingModule();
      localStorage.clear();
      vi.restoreAllMocks();
    }
  });

  it('introduces the console, says what only a terminal runs, and starts with an empty log', async () => {
    await show();

    expect(element().querySelector('h1')?.textContent?.trim()).toBe('Console');
    expect(textOf(element())).toContain('Run django_dbs commands as your own account');
    expect(textOf(element())).toContain('Run them in a terminal on that computer.');
    expect(log().getAttribute('aria-live')).toBe('polite');
    expect(log().getAttribute('dir')).toBe('ltr');
    expect(log().getAttribute('aria-label')).toBe('Commands and their output');
    expect(textOf(log())).toBe('Nothing run yet. Type help, or a command such as server list.');
    expect(field().getAttribute('dir')).toBe('ltr');
    expect(textOf(element().querySelector('[matTextPrefix]') ?? element())).toBe('django_dbs');
    expect(buttonNamed('Run')).toBeDefined();
    expect(buttonNamed('Help')).toBeDefined();
    expect(buttonNamed('Clear')?.disabled).toBe(true);
  });

  it('runs a command, shows it with its output and exit code, and empties the field', async () => {
    await show();

    const request = await run('server list', LISTED);

    expect(request.request.body).toEqual({ line: 'server list' });
    const [entry] = entries();
    expect(entry.querySelector('.console__prompt')?.getAttribute('aria-hidden')).toBe('true');
    expect(textOf(entry.querySelector('.console__line') ?? entry)).toBe('django_dbs server list');
    expect(entry.querySelector('pre')?.textContent).toBe(LISTED.output);
    expect(textOf(entry)).toContain('Done, exit code 0');
    expect(entry.classList).not.toContain('console__entry--failed');
    expect(field().value).toBe('');
  });

  it('keeps every command of the session, newest at the bottom', async () => {
    await show();

    await run('server list', LISTED);
    await run('help', HELP);

    expect(entries().map((entry) => textOf(entry.querySelector('.console__line') ?? entry))).toEqual([
      'django_dbs server list',
      'django_dbs help',
    ]);
  });

  it('marks a failed command as a failure and explains its error in the page language', async () => {
    await show();

    await run('server delete web-1', REFUSED_ROLE);

    const [entry] = entries();
    expect(entry.classList).toContain('console__entry--failed');
    expect(textOf(entry)).toContain('Failed, exit code 1');
    expect(textOf(entry)).toContain("Your account's role does not allow this.");
    const status = entry.querySelector('.console__status');
    expect(status?.getAttribute('dir')).toBe('ltr');
    TestBed.inject(LocaleStore).setLocale('ar');
    await settle();
    expect(status?.getAttribute('dir')).toBe('rtl');
    expect(textOf(entry)).toContain('فشل، رمز الخروج 1');
  });

  it('asks for the password when a command needs it, and runs the same line with it', async () => {
    await show();
    const open = stubDialog();

    await run('backup delete 7', NEEDS_PASSWORD);

    await vi.waitFor(() => expect(open).toHaveBeenCalledOnce());
    const [component, options] = open.mock.calls[0];
    expect(component).toBe(PasswordPrompt);
    const data = options.data as PasswordPromptData;
    expect(data.bodyValues).toEqual({ command: '⁨django_dbs backup delete 7⁩' });
    expect(textOf(entries()[0])).toContain('Not run: needs your password');

    const answering = data.submit('hunter2');
    const request = consoleRequest();
    expect(request.request.body).toEqual({ line: 'backup delete 7', password: 'hunter2' });
    request.flush({ ...LISTED, output: 'Deleted.\n' });
    await expect(answering).resolves.toBe(true);
    await settle();

    expect(entries()).toHaveLength(1);
    expect(textOf(entries()[0])).toContain('Done, exit code 0');
  });

  it('offers the password again for a command left unrun', async () => {
    await show();
    const open = stubDialog(undefined);

    await run('backup delete 7', NEEDS_PASSWORD);
    await vi.waitFor(() => expect(open).toHaveBeenCalledOnce());
    await settle();

    buttonNamed('Enter your password')?.click();
    await vi.waitFor(() => expect(open).toHaveBeenCalledTimes(2));
    expect(open.mock.calls[1][0]).toBe(PasswordPrompt);
  });

  it('follows each job a command started, with the way to the activity log', async () => {
    await show();

    await run('backup take shop', STARTED);
    (await vi.waitFor(() => http.expectOne(`/api/activity/${ACTIVITY_ID}/`))).flush(RUNNING_JOB);
    await settle();

    const job = entries()[0].querySelector('.console__job');
    expect(textOf(job ?? log())).toContain(`Activity ${ACTIVITY_ID}`);
    expect(textOf(job ?? log())).toContain('Running');
    expect(job?.querySelector('a')?.getAttribute('href')).toBe('/activity');
  });

  it('says when the previous command is still running', async () => {
    await show();
    await type('server list');

    buttonNamed('Run')?.click();
    consoleRequest().flush(
      { error: { code: 'console_busy', message: 'Your previous command is still running.' } },
      { status: 429, statusText: 'Too Many Requests' },
    );
    await settle();

    expect(textOf(entries()[0])).toContain('Not run');
    expect(textOf(entries()[0])).toContain('Your previous command is still running. Wait for it to finish.');
  });

  it('sends help from its button', async () => {
    await show();

    buttonNamed('Help')?.click();
    const request = consoleRequest();
    expect(request.request.body).toEqual({ line: 'help' });
    request.flush(HELP);
    await settle();

    expect(entries()[0].querySelector('pre')?.textContent).toBe(HELP.output);
  });

  it('goes back through what was run with Up and Down, and returns to the line being typed', async () => {
    await show();
    await run('server list', LISTED);
    await run('app list', LISTED);
    await type('backup');

    await press('ArrowUp');
    expect(field().value).toBe('app list');
    await press('ArrowUp');
    expect(field().value).toBe('server list');
    await press('ArrowUp');
    expect(field().value).toBe('server list');
    await press('ArrowDown');
    expect(field().value).toBe('app list');
    await press('ArrowDown');
    expect(field().value).toBe('backup');
  });

  it('clears the log', async () => {
    await show();
    await run('server list', LISTED);

    buttonNamed('Clear')?.click();
    await settle();

    expect(entries()).toHaveLength(0);
    expect(textOf(log())).toContain('Nothing run yet.');
  });
});
