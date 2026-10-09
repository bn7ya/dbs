import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { ApplicationRef } from '@angular/core';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { MatButtonHarness } from '@angular/material/button/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import type { About } from '../../data/about.types';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { AboutStore } from '../../state/about.store';
import { ABOUT, NOW } from '../../testing/about.fixtures';
import { AboutPage } from './about';

describe('AboutPage', () => {
  let http: HttpTestingController;
  let fixture: ComponentFixture<AboutPage>;

  const show = async (answer: About): Promise<HTMLElement> => {
    fixture = TestBed.createComponent(AboutPage);
    fixture.detectChanges();
    http.expectOne('/api/about/').flush(answer);
    await TestBed.inject(ApplicationRef).whenStable();
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  };

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(NOW);
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [AboutStore, provideHttpClient(withInterceptors([errorInterceptor])), provideHttpClientTesting()],
    });
    TestBed.inject(LocaleStore).register({ en, ar });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    vi.useRealTimers();
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it('shows the version, where the data is kept and when it was last exported', async () => {
    const page = await show(ABOUT);

    const facts = Array.from(page.querySelectorAll('.about__fact'), (fact) => [
      fact.querySelector('dt')?.textContent?.trim(),
      fact.querySelector('dd')?.textContent?.trim(),
    ]);
    expect(facts).toEqual([
      ['Version', ABOUT.version],
      ['Data folder', ABOUT.data_dir],
      ['Database', ABOUT.database],
      ['Backups folder', ABOUT.backups_dir],
      ['Last export', '2 days ago'],
    ]);
  });

  it('says when there has been no export yet', async () => {
    const page = await show({ ...ABOUT, last_export_at: null });

    expect(page.querySelectorAll('.about__fact dd')[4]?.textContent?.trim()).toBe('Never');
  });

  it('offers the export and import commands, each with its own copy button', async () => {
    const page = await show(ABOUT);

    expect(Array.from(page.querySelectorAll('.about__command code'), (code) => code.textContent)).toEqual([
      'django_dbs export manager.dbs',
      'django_dbs export manager.dbs --with-backups',
      'django_dbs import manager.dbs',
    ]);
    const buttons = await TestbedHarnessEnvironment.loader(fixture).getAllHarnesses(MatButtonHarness);
    expect(await Promise.all(buttons.map((button) => button.getText()))).toEqual([
      'Copy the export command',
      'Copy the export command with backups',
      'Copy the import command',
    ]);
  });

  it('says why it could not load and tries again', async () => {
    const page = await show(ABOUT);
    TestBed.inject(AboutStore).reload();
    TestBed.tick();
    http.expectOne('/api/about/').flush(
      { error: { code: 'server_error', message: 'Server prose' } },
      { status: 500, statusText: 'Server Error' },
    );
    await TestBed.inject(ApplicationRef).whenStable();
    fixture.detectChanges();
    expect(page.querySelector('app-notice[role="alert"]')).not.toBeNull();

    const retry = await TestbedHarnessEnvironment.loader(fixture).getHarness(MatButtonHarness.with({ text: 'Try again' }));
    const clicked = retry.click();
    (
      await vi.waitFor(() => {
        TestBed.tick();
        return http.expectOne('/api/about/');
      })
    ).flush(ABOUT);
    await clicked;
    await TestBed.inject(ApplicationRef).whenStable();
    fixture.detectChanges();
    expect(page.querySelector('app-notice')).toBeNull();
  });
});
