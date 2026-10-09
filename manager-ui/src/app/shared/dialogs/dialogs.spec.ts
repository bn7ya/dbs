import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MatButtonHarness } from '@angular/material/button/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatDialogHarness } from '@angular/material/dialog/testing';
import { MatInputHarness } from '@angular/material/input/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ApiError } from '@core/http/api.types';
import { LocaleStore } from '@core/i18n/locale.store';
import { PasswordPrompt } from '../password-prompt/password-prompt';
import type { PasswordPromptData } from '../password-prompt/password-prompt.types';
import { StatusTag } from '../status-tag/status-tag';
import { Dialogs } from './dialogs';

describe('Dialogs', () => {
  const submit = vi.fn<(password: string) => Promise<boolean>>();

  const data: PasswordPromptData = {
    titleKey: 'password.label',
    bodyKey: 'password.required',
    submitKey: 'actions.next',
    submit,
    error: signal<ApiError | null>(null),
  };

  const open = async () => {
    const fixture = TestBed.createComponent(StatusTag);
    fixture.componentRef.setInput('label', 'host');
    const handle = TestBed.inject(Dialogs).open<boolean, PasswordPromptData>(PasswordPrompt, {
      titleKey: 'password.label',
      data,
      size: 'sm',
    });
    const loader = TestbedHarnessEnvironment.documentRootLoader(fixture);
    return { handle, dialog: await loader.getHarness(MatDialogHarness) };
  };

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [Dialogs, { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } }],
    });
    TestBed.inject(LocaleStore);
    submit.mockReset();
  });

  afterEach(() => {
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it('frames the component with its translated title and gives it the data', async () => {
    const { dialog } = await open();

    expect(await dialog.getTitleText()).toBe('Your password');
    expect(await dialog.getContentText()).toContain('Enter your password.');
    await dialog.close();
  });

  it('closes with what the component closes with', async () => {
    submit.mockResolvedValue(true);
    const { handle, dialog } = await open();

    await (await dialog.getHarness(MatInputHarness)).setValue('secret');
    await (await dialog.getHarness(MatButtonHarness.with({ text: 'Next' }))).click();

    await expect(handle.whenClosed()).resolves.toBe(true);
    expect(submit).toHaveBeenCalledWith('secret');
  });

  it('closes with nothing when the reader dismisses it', async () => {
    const { handle, dialog } = await open();

    await (await dialog.getHarness(MatButtonHarness.with({ selector: '.dialog-frame__close' }))).click();

    await expect(handle.whenClosed()).resolves.toBeUndefined();
  });
});
