import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { DOCUMENT } from '@angular/common';
import { TestBed } from '@angular/core/testing';
import { MatButtonHarness } from '@angular/material/button/testing';
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';

import { Toaster } from '../toaster/toaster';
import { CopyButton } from './copy-button';

describe('CopyButton', () => {
  let add: MockInstance<Toaster['add']>;

  const press = async (): Promise<void> => {
    const fixture = TestBed.createComponent(CopyButton);
    fixture.componentRef.setInput('text', 'django_dbs export manager.dbs');
    fixture.componentRef.setInput('label', 'Copy');
    await (await TestbedHarnessEnvironment.loader(fixture).getHarness(MatButtonHarness.with({ text: 'Copy' }))).click();
    await fixture.whenStable();
  };

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    add = vi.spyOn(TestBed.inject(Toaster), 'add').mockReturnValue(undefined);
  });

  afterEach(() => {
    TestBed.resetTestingModule();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('copies its text and says so', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(TestBed.inject(DOCUMENT).defaultView?.navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    });

    await press();

    expect(writeText).toHaveBeenCalledWith('django_dbs export manager.dbs');
    expect(add).toHaveBeenCalledWith({ severity: 'success', summary: 'Copied.' });
  });

  it('says so when the browser refuses', async () => {
    Object.defineProperty(TestBed.inject(DOCUMENT).defaultView?.navigator, 'clipboard', {
      value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
      configurable: true,
    });

    await press();

    expect(add).toHaveBeenCalledWith(expect.objectContaining({ severity: 'warning' }));
  });
});
