import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { TestBed } from '@angular/core/testing';
import { MatButtonHarness } from '@angular/material/button/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatDialogHarness } from '@angular/material/dialog/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { StatusTag } from '../status-tag/status-tag';
import { Confirmation } from './confirmation';

describe('Confirmation', () => {
  const options = {
    title: 'Delete the server?',
    message: 'The server is removed.',
    detail: 'Backups stay on the server.',
    acceptLabel: 'Delete',
    rejectLabel: 'Keep it',
    acceptSeverity: 'danger' as const,
  };

  const open = async (): Promise<{ answer: Promise<boolean>; dialog: MatDialogHarness }> => {
    const fixture = TestBed.createComponent(StatusTag);
    fixture.componentRef.setInput('label', 'host');
    const answer = TestBed.inject(Confirmation).ask(options);
    const loader = TestbedHarnessEnvironment.documentRootLoader(fixture);
    return { answer, dialog: await loader.getHarness(MatDialogHarness) };
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [{ provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } }],
    });
  });

  afterEach(() => {
    TestBed.resetTestingModule();
  });

  it('asks with the title, the message and its detail', async () => {
    const { dialog } = await open();

    expect(await dialog.getTitleText()).toBe('Delete the server?');
    expect(await dialog.getContentText()).toContain('The server is removed.');
    expect(await dialog.getContentText()).toContain('Backups stay on the server.');
    expect(await dialog.getRole()).toBe('alertdialog');
    await dialog.close();
  });

  it('answers yes when the reader accepts', async () => {
    const { answer, dialog } = await open();

    await (await dialog.getHarness(MatButtonHarness.with({ text: 'Delete' }))).click();

    await expect(answer).resolves.toBe(true);
  });

  it('answers no when the reader keeps it or dismisses the dialog', async () => {
    const first = await open();
    await (await first.dialog.getHarness(MatButtonHarness.with({ text: 'Keep it' }))).click();
    await expect(first.answer).resolves.toBe(false);

    const second = await open();
    await second.dialog.close();
    await expect(second.answer).resolves.toBe(false);
  });
});
