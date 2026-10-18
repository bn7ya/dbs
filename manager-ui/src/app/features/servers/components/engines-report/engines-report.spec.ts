import { TestBed } from '@angular/core/testing';
import { afterEach, describe, expect, it } from 'vitest';

import { LocaleStore } from '@core/i18n/locale.store';
import type { ServerCheckReport } from '../../data/servers.types';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { EnginesReport } from './engines-report';

describe('EnginesReport', () => {
  const render = async (report: ServerCheckReport): Promise<string> => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({});
    TestBed.inject(LocaleStore).register({ en, ar });
    const fixture = TestBed.createComponent(EnginesReport);
    fixture.componentRef.setInput('report', report);
    await fixture.whenStable();
    return (fixture.nativeElement as HTMLElement).textContent?.replace(/\s+/g, ' ') ?? '';
  };

  afterEach(() => {
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it('names each engine with its version and Compose, or says it is not there', async () => {
    const text = await render({
      system: 'Linux 6.8.0',
      engines: {
        docker: { installed: true, usable: true, version: '27.3.1', compose: '2.29.7', error: '' },
        podman: { installed: false, usable: false, version: null, compose: null, error: '' },
      },
      timeout: true,
    });

    expect(text).toContain('27.3.1');
    expect(text).toContain('Compose 2.29.7');
    expect(text).toContain('Not installed');
    expect(text).toContain('Found');
    expect(text).not.toContain('Add the user');
  });

  it('explains a refused engine and repeats what a broken one said', async () => {
    const text = await render({
      system: null,
      engines: {
        docker: { installed: true, usable: false, version: null, compose: null, error: 'engine_permission_denied' },
        podman: { installed: true, usable: false, version: null, compose: null, error: 'cannot connect to podman' },
      },
      timeout: null,
    });

    expect(text).toContain('Installed, but the SSH user may not use it');
    expect(text).toContain('Add the user to the engine');
    expect(text).toContain('Installed, but it did not answer');
    expect(text).toContain('It said: cannot connect to podman');
    expect(text).not.toContain('engine_permission_denied');
  });
});
