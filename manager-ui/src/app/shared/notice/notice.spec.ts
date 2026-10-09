import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { MatButtonHarness } from '@angular/material/button/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Notice } from './notice';

describe('Notice', () => {
  let fixture: ComponentFixture<Notice>;

  const host = (): HTMLElement => {
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  };

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    fixture = TestBed.createComponent(Notice);
  });

  afterEach(() => {
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it('is a status for information and success, and an alert for a warning or a failure', () => {
    expect(host().getAttribute('role')).toBe('status');

    fixture.componentRef.setInput('severity', 'success');
    expect(host().getAttribute('role')).toBe('status');

    fixture.componentRef.setInput('severity', 'warning');
    expect(host().getAttribute('role')).toBe('alert');

    fixture.componentRef.setInput('severity', 'danger');
    expect(host().getAttribute('role')).toBe('alert');
    expect(host().classList).toContain('notice--danger');
  });

  it('offers a close button only when it can be closed, and says when it was', async () => {
    const loader = TestbedHarnessEnvironment.loader(fixture);
    expect(await loader.getAllHarnesses(MatButtonHarness)).toHaveLength(0);

    const closed = vi.fn();
    fixture.componentInstance.closed.subscribe(closed);
    fixture.componentRef.setInput('closable', true);

    const close = await loader.getHarness(MatButtonHarness);
    expect(await (await close.host()).getAttribute('aria-label')).toBe('Close');
    await close.click();
    expect(closed).toHaveBeenCalledTimes(1);
  });
});
