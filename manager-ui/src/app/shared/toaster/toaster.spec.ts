import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { TestBed } from '@angular/core/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatSnackBarHarness } from '@angular/material/snack-bar/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { StatusTag } from '../status-tag/status-tag';
import { Toaster } from './toaster';

describe('Toaster', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [{ provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } }],
    });
  });

  afterEach(() => {
    TestBed.resetTestingModule();
  });

  it('shows the summary and the detail, announcing a failure at once', async () => {
    const fixture = TestBed.createComponent(StatusTag);
    fixture.componentRef.setInput('label', 'host');
    TestBed.inject(Toaster).add({ severity: 'danger', summary: 'Backup failed.', detail: 'The server did not answer.' });

    const toast = await TestbedHarnessEnvironment.documentRootLoader(fixture).getHarness(MatSnackBarHarness);

    expect(await toast.getMessage()).toContain('Backup failed.');
    expect(await toast.getMessage()).toContain('The server did not answer.');
    expect(await toast.getAriaLive()).toBe('assertive');
  });
});
