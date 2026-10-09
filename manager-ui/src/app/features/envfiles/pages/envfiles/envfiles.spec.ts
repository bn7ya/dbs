import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, type TestRequest } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter, withComponentInputBinding, type Routes } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { ConfirmationService, MessageService } from 'primeng/api';
import { of } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';

import type { Identity } from '@core/auth/data/auth.types';
import type { Page } from '@core/http/api.types';
import { errorInterceptor } from '@core/http/error.interceptor';
import { Confirmation } from '@shared/confirm/confirmation';
import { Dialogs } from '@shared/dialogs/dialogs';
import type { DialogHandle } from '@shared/dialogs/dialogs.types';
import { PasswordPrompt } from '@shared/password-prompt/password-prompt';
import type { PasswordPromptData } from '@shared/password-prompt/password-prompt.types';
import { Toaster } from '@shared/toaster/toaster';
import type { ToastMessage } from '@shared/toaster/toaster.types';
import type { EnvVersion } from '../../data/envfiles.types';
import { EnvfilesStore } from '../../state/envfiles.store';
import { COMPARISON, CONTENT, ENV_PATH, OLDER, OLDEST, SERVER_ID, VERSION, pageOf } from '../../testing/envfiles.fixtures';
import { EnvfilesPage } from './envfiles';

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
  {
    path: 'servers/:serverId',
    children: [
      { path: 'environment', loadChildren: () => import('../../envfiles.routes').then((m) => m.routes) },
      { path: 'files', children: [] },
    ],
  },
];

const BLOB_URL = 'blob:http://localhost/env';

describe('EnvfilesPage', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;
  let toasts: MockInstance<(message: ToastMessage) => void>;
  const clipboard = { writeText: vi.fn<(text: string) => Promise<void>>() };
  const createObjectURL = vi.fn<(blob: Blob) => string>(() => BLOB_URL);
  const revokeObjectURL = vi.fn<(url: string) => void>();
  const urlBefore: PropertyDescriptorMap = Object.getOwnPropertyDescriptors(URL);
  const clipboardBefore = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
  const stubUrl = (statics: Readonly<Record<'createObjectURL' | 'revokeObjectURL', unknown>>): void => {
    for (const [name, value] of Object.entries(statics)) {
      Object.defineProperty(URL, name, { value, configurable: true, writable: true });
    }
  };
  const restoreClipboard = (): void => {
    if (clipboardBefore === undefined) {
      Reflect.deleteProperty(navigator, 'clipboard');
    } else {
      Object.defineProperty(navigator, 'clipboard', clipboardBefore);
    }
  };
  const restoreUrl = (): void => {
    for (const name of ['createObjectURL', 'revokeObjectURL']) {
      const descriptor = urlBefore[name];
      if (descriptor === undefined) {
        Reflect.deleteProperty(URL, name);
      } else {
        Object.defineProperty(URL, name, descriptor);
      }
    }
  };

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const listRequest = (): TestRequest =>
    http.expectOne((request) => request.url === '/api/envfiles/' && request.method === 'GET');

  const showWith = async (page: Page<EnvVersion>, envPath = ENV_PATH): Promise<EnvfilesPage> => {
    harness = await RouterTestingHarness.create();
    const navigating = harness.navigateByUrl(`/servers/${SERVER_ID}/environment`, EnvfilesPage);
    (await vi.waitFor(() => http.expectOne('/api/auth/me/'))).flush(IDENTITY);
    const shown = await navigating;
    TestBed.tick();
    http.expectOne(`/api/servers/${SERVER_ID}/`).flush({ id: SERVER_ID, env_path: envPath });
    listRequest().flush(page);
    await settle();
    harness.detectChanges();
    return shown;
  };

  const element = (): HTMLElement => harness.routeNativeElement as HTMLElement;
  const rows = (): HTMLElement[] => Array.from(element().querySelectorAll<HTMLElement>('p-table tbody tr'));
  const cards = (): HTMLElement[] => Array.from(element().querySelectorAll<HTMLElement>('.envfiles > p-card'));
  const buttonNamed = (text: string): HTMLButtonElement | undefined =>
    Array.from(element().querySelectorAll('button')).find((button) => button.textContent?.trim() === text);

  const stubDialog = (): MockInstance<Dialogs['open']> => {
    const handle: DialogHandle<unknown> = { closed: of(true), whenClosed: () => Promise.resolve(true) };
    const page = harness.routeDebugElement;
    if (page === null) {
      throw new Error('The page is not on screen.');
    }
    return vi.spyOn(page.injector.get(Dialogs), 'open').mockReturnValue(handle);
  };

  const promptData = (open: MockInstance<Dialogs['open']>): PasswordPromptData => {
    const [component, options] = open.mock.calls[0];
    expect(component).toBe(PasswordPrompt);
    const data = options.data as PasswordPromptData;
    expect(options.titleKey).toBe(data.titleKey);
    return data;
  };

  const reveal = async (): Promise<void> => {
    const open = stubDialog();
    buttonNamed('Show values')?.click();
    await vi.waitFor(() => expect(open).toHaveBeenCalledOnce());
    const submitting = promptData(open).submit('hunter2');
    http.expectOne(`/api/envfiles/${VERSION.id}/reveal/`).flush({ content: CONTENT });
    await expect(submitting).resolves.toBe(true);
    harness.detectChanges();
    await settle();
    harness.detectChanges();
  };

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    stubUrl({ createObjectURL, revokeObjectURL });
    Object.defineProperty(navigator, 'clipboard', { value: clipboard, configurable: true });
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter(ROUTES, withComponentInputBinding()),
        MessageService,
        ConfirmationService,
      ],
    });
    http = TestBed.inject(HttpTestingController);
    toasts = vi.spyOn(TestBed.inject(Toaster), 'add').mockReturnValue(undefined);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
    vi.restoreAllMocks();
    vi.clearAllMocks();
    restoreUrl();
    restoreClipboard();
  });

  it('lists the versions under a second-level title, with where the file is, and shows the newest', async () => {
    const page = await showWith(pageOf([VERSION, OLDER, OLDEST]));

    expect(page.serverId()).toBe(SERVER_ID);
    expect(element().querySelector('h1')).toBeNull();
    expect(element().querySelector('h2')?.textContent?.trim()).toBe('.env file');
    const path = cards()[0].querySelector('bdi[dir="ltr"]');
    expect(path?.textContent).toBe(ENV_PATH);
    expect(buttonNamed('Pull now')).toBeDefined();

    expect(rows()).toHaveLength(3);
    expect(rows().map((row) => row.querySelector('p-tag')?.textContent?.trim())).toEqual([
      'Pulled',
      'Daily snapshot',
      'Pushed',
    ]);
    expect(rows()[0].textContent).toContain('By ⁨sara⁩');
    expect(rows()[1].textContent).not.toContain('By');
    expect(rows()[0].querySelector('button')?.getAttribute('aria-current')).toBe('true');
    expect(rows()[1].querySelector('button')?.getAttribute('aria-current')).toBeNull();
  });

  it('shows the key names of the selected version with every value masked', async () => {
    await showWith(pageOf([VERSION, OLDER]));

    const detail = cards()[1];
    expect(detail.querySelector('h2')?.textContent?.trim()).toBe('Selected version');
    expect(detail.querySelector('h3')?.textContent?.trim()).toBe('Keys: 3');
    const keys = Array.from(detail.querySelectorAll('.envfiles__pair dt bdi'));
    expect(keys.map((key) => key.textContent)).toEqual(VERSION.keys);
    expect(keys.every((key) => key.getAttribute('dir') === 'ltr')).toBe(true);
    const masks = Array.from(detail.querySelectorAll('.envfiles__mask'));
    expect(masks).toHaveLength(3);
    expect(masks[0].getAttribute('aria-label')).toBe('Value hidden');
    expect(masks[0].textContent?.trim()).toBe('••••••');
    expect(detail.textContent).not.toContain('s3cr3t');
    expect(element().querySelector('textarea')).toBeNull();
  });

  it('shows another version when its row is chosen', async () => {
    await showWith(pageOf([VERSION, OLDER, OLDEST]));

    rows()[2].querySelector('button')?.click();
    harness.detectChanges();

    expect(rows()[2].querySelector('button')?.getAttribute('aria-current')).toBe('true');
    expect(rows()[0].querySelector('button')?.getAttribute('aria-current')).toBeNull();
    expect(cards()[1].querySelector('h3')?.textContent?.trim()).toBe('Keys: 1');
    // The first version kept has nothing before it to compare with.
    expect(buttonNamed('Compare with the previous version')).toBeUndefined();
    expect(cards()[1].textContent).toContain('This is the first version kept.');
  });

  it('sends a server with no .env file set to its overview, with nothing to pull', async () => {
    await showWith(pageOf([]), '');

    const empty = element().querySelector('app-empty-state');
    expect(empty?.textContent).toContain('No .env file set');
    expect(empty?.querySelector('a')?.getAttribute('href')).toBe(`/servers/${SERVER_ID}`);
    expect(buttonNamed('Pull now')).toBeUndefined();
    expect(cards()).toHaveLength(1);
  });

  it('keeps the versions of a server whose .env file is no longer set, with nothing to pull or push', async () => {
    await showWith(pageOf([VERSION]), '');

    expect(element().querySelector('p-message')?.textContent).toContain('This server has no .env file set.');
    expect(rows()).toHaveLength(1);
    expect(buttonNamed('Pull now')).toBeUndefined();
    expect(buttonNamed('Push this version to the server')).toBeUndefined();
    expect(buttonNamed('Show values')).toBeDefined();
  });

  it('offers the first pull when no version is kept yet', async () => {
    await showWith(pageOf([]));

    const empty = element().querySelector('app-empty-state');
    expect(empty?.textContent).toContain('No versions yet');
    const pull = Array.from(element().querySelectorAll('button')).filter(
      (button) => button.textContent?.trim() === 'Pull now',
    );
    expect(pull).toHaveLength(1);

    pull[0].click();
    http.expectOne('/api/envfiles/pull/').flush({ created: true, version: VERSION });
    await vi.waitFor(() => expect(toasts).toHaveBeenCalledWith({ severity: 'success', summary: 'New version kept.' }));
    TestBed.tick();
    listRequest().flush(pageOf([VERSION]));
    await settle();
    harness.detectChanges();
    expect(rows()).toHaveLength(1);
  });

  describe('the values', () => {
    it("asks for the reader's password, then shows the file read-only, left to right, unchecked", async () => {
      await showWith(pageOf([VERSION, OLDER]));
      const open = stubDialog();

      buttonNamed('Show values')?.click();
      await vi.waitFor(() => expect(open).toHaveBeenCalledOnce());
      const data = promptData(open);
      expect(data).toMatchObject({
        titleKey: 'envfiles.reveal.prompt.title',
        bodyKey: 'envfiles.reveal.prompt.body',
        submitKey: 'envfiles.reveal.show',
      });
      const submitting = data.submit('hunter2');
      const request = http.expectOne(`/api/envfiles/${VERSION.id}/reveal/`);
      expect(request.request.body).toEqual({ password: 'hunter2' });
      request.flush({ content: CONTENT });
      await submitting;
      harness.detectChanges();
      await settle();
      harness.detectChanges();

      const box = element().querySelector('textarea');
      expect(box?.value).toBe(CONTENT);
      expect(box?.readOnly).toBe(true);
      expect(box?.getAttribute('dir')).toBe('ltr');
      expect(box?.getAttribute('spellcheck')).toBe('false');
      expect(box?.getAttribute('autocomplete')).toBe('off');
      expect(element().querySelector('.envfiles__pairs')).toBeNull();
      expect(buttonNamed('Hide values')).toBeDefined();
    });

    it('downloads the content as a file named after the path, from a blob that goes with it', async () => {
      await showWith(pageOf([VERSION]));
      await reveal();

      expect(createObjectURL).toHaveBeenCalledOnce();
      const blob = createObjectURL.mock.calls[0][0];
      await expect(blob.text()).resolves.toBe(CONTENT);
      const link = element().querySelector<HTMLAnchorElement>('a[download]');
      expect(link?.getAttribute('href')).toBe(BLOB_URL);
      expect(link?.getAttribute('download')).toBe('.env');
      expect(link?.textContent?.trim()).toBe('Download as file');

      buttonNamed('Hide values')?.click();
      harness.detectChanges();
      await settle();

      expect(element().querySelector('textarea')).toBeNull();
      expect(element().querySelector('a[download]')).toBeNull();
      expect(revokeObjectURL).toHaveBeenCalledWith(BLOB_URL);
    });

    it('copies the content, and says so', async () => {
      clipboard.writeText.mockResolvedValue(undefined);
      await showWith(pageOf([VERSION]));
      await reveal();

      buttonNamed('Copy content')?.click();

      await vi.waitFor(() => expect(clipboard.writeText).toHaveBeenCalledWith(CONTENT));
      await vi.waitFor(() => expect(toasts).toHaveBeenCalledWith({ severity: 'success', summary: 'Content copied.' }));
    });

    it('takes the content away when another version is chosen', async () => {
      await showWith(pageOf([VERSION, OLDER]));
      await reveal();

      rows()[1].querySelector('button')?.click();
      harness.detectChanges();

      expect(element().querySelector('textarea')).toBeNull();
      expect(buttonNamed('Show values')).toBeDefined();
    });

    it('takes the content out of the store and releases its blob when the reader leaves the tab', async () => {
      await showWith(pageOf([VERSION]));
      const store = harness.routeDebugElement?.injector.get(EnvfilesStore);
      await reveal();
      expect(store?.content()).toBe(CONTENT);

      await TestBed.inject(Router).navigateByUrl(`/servers/${SERVER_ID}/files`);

      expect(store?.content()).toBeNull();
      expect(revokeObjectURL).toHaveBeenCalledWith(BLOB_URL);
    });
  });

  it('compares the selected version with the one before it', async () => {
    await showWith(pageOf([VERSION, OLDER]));

    buttonNamed('Compare with the previous version')?.click();
    (await vi.waitFor(() => http.expectOne(`/api/envfiles/${OLDER.id}/compare/?to=${VERSION.id}`))).flush(COMPARISON);
    await settle();
    harness.detectChanges();

    const detail = cards()[1];
    expect(Array.from(detail.querySelectorAll('h3')).map((heading) => heading.textContent?.trim())).toContain(
      'Changes since the previous version',
    );
    const groups = Array.from(detail.querySelectorAll('.envfiles__changes .envfiles__fact'));
    expect(groups.map((group) => group.querySelector('dt')?.textContent?.trim())).toEqual([
      'Added keys',
      'Removed keys',
      'Changed values',
    ]);
    expect(groups.map((group) => group.querySelector('bdi')?.textContent)).toEqual(['SECRET_KEY', 'OLD_FLAG', 'DEBUG']);
    expect(buttonNamed('Compare with the previous version')).toBeUndefined();
  });

  it('says when nothing changed, values included', async () => {
    await showWith(pageOf([VERSION, OLDER]));

    buttonNamed('Compare with the previous version')?.click();
    (await vi.waitFor(() => http.expectOne(`/api/envfiles/${OLDER.id}/compare/?to=${VERSION.id}`))).flush({
      ...COMPARISON,
      added: [],
      removed: [],
      changed: [],
    });
    await settle();
    harness.detectChanges();

    expect(cards()[1].querySelector('p-message')?.textContent).toContain('No difference in keys or values.');
  });

  describe('pushing a version back', () => {
    it('asks first, naming the file it replaces, then asks for the password and pushes', async () => {
      await showWith(pageOf([VERSION, OLDER]));
      const ask = vi.spyOn(TestBed.inject(Confirmation), 'ask').mockResolvedValue(true);
      const open = stubDialog();
      rows()[1].querySelector('button')?.click();
      harness.detectChanges();

      buttonNamed('Push this version to the server')?.click();

      await vi.waitFor(() => expect(ask).toHaveBeenCalledOnce());
      expect(ask.mock.calls[0][0]).toMatchObject({
        title: 'Replace the .env file on the server?',
        message: `⁦${ENV_PATH}⁩`,
        detail: 'The file on the server now is kept as a version first. Then this version takes its place.',
        acceptLabel: 'Continue',
      });
      await vi.waitFor(() => expect(open).toHaveBeenCalledOnce());
      const data = promptData(open);
      expect(data.submitKey).toBe('envfiles.push.prompt.submit');

      const pushing = data.submit('hunter2');
      const pushed: EnvVersion = { ...OLDER, id: '7a1e4c20-5555-4d3b-8c9f-1e2d3c4b0009', source: 'pushed' };
      http.expectOne(`/api/envfiles/${OLDER.id}/push/`).flush({ version: pushed });
      await expect(pushing).resolves.toBe(true);
      expect(toasts).toHaveBeenCalledWith({ severity: 'success', summary: 'Version pushed to the server.' });
      TestBed.tick();
      listRequest().flush(pageOf([pushed, VERSION, OLDER]));
      await settle();
      harness.detectChanges();
      expect(rows()[0].querySelector('button')?.getAttribute('aria-current')).toBe('true');
    });

    it('pushes nothing when the reader says no', async () => {
      await showWith(pageOf([VERSION]));
      const ask = vi.spyOn(TestBed.inject(Confirmation), 'ask').mockResolvedValue(false);
      const open = stubDialog();

      buttonNamed('Push this version to the server')?.click();

      await vi.waitFor(() => expect(ask).toHaveBeenCalledOnce());
      expect(open).not.toHaveBeenCalled();
      http.expectNone((request) => request.method === 'POST');
    });
  });

  it('says why the versions could not be listed, and tries again', async () => {
    harness = await RouterTestingHarness.create();
    const navigating = harness.navigateByUrl(`/servers/${SERVER_ID}/environment`, EnvfilesPage);
    (await vi.waitFor(() => http.expectOne('/api/auth/me/'))).flush(IDENTITY);
    await navigating;
    TestBed.tick();
    http.expectOne(`/api/servers/${SERVER_ID}/`).flush({ id: SERVER_ID, env_path: ENV_PATH });
    listRequest().flush({ error: { code: 'network', message: 'Server prose' } }, { status: 503, statusText: 'Down' });
    await settle();
    harness.detectChanges();

    expect(element().querySelector('p-message')?.textContent).toContain("Can't reach DBS Interface.");
    buttonNamed('Try again')?.click();
    TestBed.tick();
    listRequest().flush(pageOf([VERSION]));
    await settle();
    harness.detectChanges();
    expect(rows()).toHaveLength(1);
  });
});
