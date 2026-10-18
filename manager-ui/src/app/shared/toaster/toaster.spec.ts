import { Directionality } from '@angular/cdk/bidi';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { TestBed } from '@angular/core/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatSnackBarHarness } from '@angular/material/snack-bar/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AppDirectionality } from '@core/i18n/app-directionality';
import { LocaleStore } from '@core/i18n/locale.store';
import { StatusTag } from '../status-tag/status-tag';
import { Toaster } from './toaster';

describe('Toaster', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
        { provide: Directionality, useExisting: AppDirectionality },
      ],
    });
  });

  afterEach(() => {
    TestBed.resetTestingModule();
    localStorage.clear();
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

  it('opens at the end of the reading direction, the left edge in Arabic', () => {
    const opened = vi.spyOn(TestBed.inject(MatSnackBar), 'openFromComponent');
    const locale = TestBed.inject(LocaleStore);
    const toaster = TestBed.inject(Toaster);

    locale.setLocale('en');
    TestBed.tick();
    toaster.add({ severity: 'success', summary: 'Saved.' });
    locale.setLocale('ar');
    TestBed.tick();
    toaster.add({ severity: 'success', summary: 'Saved.' });

    expect(opened.mock.calls.map(([, config]) => [config?.horizontalPosition, config?.direction])).toEqual([
      ['end', 'ltr'],
      ['end', 'rtl'],
    ]);
  });
});
