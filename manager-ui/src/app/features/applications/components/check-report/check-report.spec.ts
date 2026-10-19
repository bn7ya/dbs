import { TestBed } from '@angular/core/testing';
import { afterEach, describe, expect, it } from 'vitest';

import { LocaleStore } from '@core/i18n/locale.store';
import type { Application, Compatibility } from '../../data/applications.types';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { APPLICATION } from '../../testing/applications.fixtures';
import { CheckReport } from './check-report';

describe('CheckReport', () => {
  const render = async (application: Application, versions: Compatibility | null = null): Promise<string> => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({});
    TestBed.inject(LocaleStore).register({ en, ar });
    const fixture = TestBed.createComponent(CheckReport);
    fixture.componentRef.setInput('application', application);
    fixture.componentRef.setInput('versions', versions);
    await fixture.whenStable();
    return (fixture.nativeElement as HTMLElement).textContent ?? '';
  };

  afterEach(() => {
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it('shows what the check found in a container, and the two versions when it just ran', async () => {
    const text = await render(APPLICATION, { local_version: '0.8.0', remote_version: '0.8.0', installed: true, compatible: true });

    expect(text).toContain('django-dbs here');
    expect(text).toContain('27.3.1');
    expect(text).toContain('Running');
    expect(text).toContain('/app/media');
    expect(text).toContain('django-dbs here and in the application work together.');
    expect(text).not.toContain('also schedules backups');
  });

  it('says an old django-dbs does not work with this manager', async () => {
    const text = await render(APPLICATION, { local_version: '0.8.0', remote_version: '0.6.0', installed: true, compatible: false });

    expect(text).toContain('too old for this manager');
  });

  it('names the Python that could not import django-dbs and why', async () => {
    const text = await render({
      ...APPLICATION,
      last_check_report: { ...APPLICATION.last_check_report, dbs_version: null, dbs_error: "No module named 'dbs'" },
    });

    expect(text).toContain('django-dbs was not found with');
    expect(text).toContain('/app/.venv/bin/python');
    expect(text).toContain("No module named 'dbs'");
  });

  it('warns when the application’s own panel also schedules backups, and says what the engine said', async () => {
    const text = await render({
      ...APPLICATION,
      last_check_report: {
        ...APPLICATION.last_check_report,
        container: { engine: 'docker', version: '27.3.1', error: 'no such service: web', running: false },
        panel_schedule: { enabled: true, mode: 'thread' },
      },
    });

    expect(text).toContain('Not running');
    expect(text).toContain('no such service: web');
    expect(text).toContain('also schedules backups');
  });

  it('says a .env file is not set rather than missing', async () => {
    const text = await render({ ...APPLICATION, env_path: '', kind: 'host', engine: '' });

    expect(text).toContain('Not set');
    expect(text).not.toContain('The timeout command inside the container');
  });
});
