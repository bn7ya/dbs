import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ApplicationRef, type Type } from '@angular/core';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import coreAr from '@core/i18n/ar.json';
import coreEn from '@core/i18n/en.json';
import { Dialogs } from '@shared/dialogs/dialogs';
import type { DialogOptions } from '@shared/dialogs/dialogs.types';
import type { PasswordPromptData } from '@shared/password-prompt/password-prompt.types';
import type { ManagerRelease } from '../../data/about.types';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { AboutStore } from '../../state/about.store';
import { ManagerUpdate } from './manager-update';

const UPDATE = '/api/about/update/';

const NEWER: ManagerRelease = { current: '0.9.0', latest: '0.9.1', newer: true, refusal: null, busy: false };

describe('ManagerUpdate', () => {
  let http: HttpTestingController;
  let fixture: ComponentFixture<ManagerUpdate>;
  let typed: string[];
  let prompts: DialogOptions<PasswordPromptData>[];

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const page = (): HTMLElement => {
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  };

  const button = (text: string): HTMLButtonElement | undefined =>
    Array.from(page().querySelectorAll('button')).find((found) => found.textContent?.trim() === text);

  const looked = async (answer: ManagerRelease): Promise<void> => {
    button('Look for a newer release')?.click();
    http.expectOne(UPDATE).flush(answer);
    await settle();
  };

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    typed = [];
    prompts = [];
    TestBed.configureTestingModule({
      providers: [
        AboutStore,
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        {
          provide: Dialogs,
          useValue: {
            open: (_component: Type<unknown>, options: DialogOptions<PasswordPromptData>) => ({
              whenClosed: async () => {
                prompts.push(options);
                for (const password of typed) {
                  if (await options.data?.submit(password)) {
                    return true;
                  }
                }
                return undefined;
              },
            }),
          },
        },
      ],
    });
    TestBed.inject(LocaleStore).register({ en: { ...coreEn, ...en }, ar: { ...coreAr, ...ar } });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(ManagerUpdate);
    TestBed.tick();
    http.expectOne('/api/about/').flush({});
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('asks nothing of PyPI until it is told to look', () => {
    expect(page().textContent).toContain('Install a newer django-dbs for this manager.');
    http.expectNone(UPDATE);
  });

  it('says when a newer release is available, and offers to install it', async () => {
    await looked(NEWER);

    expect(page().textContent).toContain('django-dbs 0.9.1 is available. This manager runs 0.9.0.');
    expect(button('Install 0.9.1')).toBeDefined();
  });

  it('says when this is the newest release, and when PyPI did not answer', async () => {
    await looked({ ...NEWER, latest: '0.9.0', newer: false });
    expect(page().textContent).toContain('django-dbs 0.9.0 is the newest release.');
    expect(button('Install 0.9.0')).toBeUndefined();

    await looked({ ...NEWER, latest: null, newer: false });
    expect(page().textContent).toContain('PyPI did not answer');
  });

  it('says why this manager cannot be updated from here, and offers no install', async () => {
    await looked({ ...NEWER, refusal: 'update_source_checkout' });
    expect(page().textContent).toContain('This manager runs from a source checkout. Update it with git.');
    expect(button('Install 0.9.1')).toBeUndefined();

    await looked({ ...NEWER, busy: true });
    expect(page().textContent).toContain('A job is running or a terminal is open.');
    expect(button('Install 0.9.1')).toBeUndefined();
  });

  it('says why it could not look', async () => {
    button('Look for a newer release')?.click();
    http
      .expectOne(UPDATE)
      .flush({ error: { code: 'role_required', message: 'Server prose' } }, { status: 403, statusText: 'Forbidden' });
    await settle();

    expect(page().querySelector('app-notice[role="alert"]')).not.toBeNull();
  });

  it('installs behind the password, says the manager is restarting, and reloads when asked', async () => {
    await looked(NEWER);
    typed = ['hunter2'];

    button('Install 0.9.1')?.click();
    await vi.waitFor(() => {
      const request = http.expectOne(UPDATE);
      expect(request.request.method).toBe('POST');
      expect(request.request.body).toEqual({ password: 'hunter2' });
      request.flush({ version: '0.9.1', updated: true, restarting: true });
    });
    await settle();

    expect(prompts[0].data?.bodyValues).toEqual({ version: '0.9.1' });
    expect(page().textContent).toContain('django-dbs 0.9.1 is installed and the manager is restarting.');
    const reloaded = vi.spyOn(fixture.componentInstance, 'reload').mockReturnValue(undefined);
    button('Reload')?.click();
    expect(reloaded).toHaveBeenCalledOnce();
  });

  it('keeps a wrong password for the prompt to say, and installs nothing', async () => {
    await looked(NEWER);
    typed = ['wrong'];

    button('Install 0.9.1')?.click();
    await vi.waitFor(() => {
      http
        .expectOne(UPDATE)
        .flush({ error: { code: 'invalid_password', message: 'Server prose' } }, { status: 403, statusText: 'Forbidden' });
    });
    await settle();

    expect(TestBed.inject(AboutStore).installError()?.code).toBe('invalid_password');
    expect(page().textContent).not.toContain('is installed');
  });
});
