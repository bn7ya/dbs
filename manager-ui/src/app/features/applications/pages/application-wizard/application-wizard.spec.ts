import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import type { Type } from '@angular/core';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MatButtonHarness } from '@angular/material/button/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatRadioGroupHarness } from '@angular/material/radio/testing';
import { MatStepperHarness } from '@angular/material/stepper/testing';
import { provideRouter, type Routes } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { Subject } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import { JobWatcher } from '@core/jobs/job-watcher';
import type { Job } from '@core/jobs/job.types';
import { Dialogs } from '@shared/dialogs/dialogs';
import type { DialogOptions } from '@shared/dialogs/dialogs.types';
import type { PasswordPromptData } from '@shared/password-prompt/password-prompt.types';
import type { CheckedApplication, Discovery } from '../../data/applications.types';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { ApplicationWizardStore } from '../../state/application-wizard.store';
import { APPLICATION, CHECKED, DISCOVERY, HOST, NO_FOLDER, SERVER_ID } from '../../testing/applications.fixtures';
import { ApplicationWizardPage } from './application-wizard';

const ROUTES: Routes = [
  {
    path: 'servers/:serverId/applications/new',
    providers: [ApplicationWizardStore],
    component: ApplicationWizardPage,
  },
];

const DETAIL = `/api/applications/${APPLICATION.id}/`;

describe('ApplicationWizardPage', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;
  let wizard: ApplicationWizardPage;
  let typed: string[];
  let jobs: Subject<Job>;
  let prompted: Mock<(component: Type<unknown>, options: DialogOptions<PasswordPromptData>) => Promise<true | undefined>>;

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const html = (): HTMLElement => {
    harness.detectChanges();
    return harness.routeNativeElement as HTMLElement;
  };

  const discover = async (found: Discovery = DISCOVERY): Promise<void> => {
    (await vi.waitFor(() => http.expectOne('/api/applications/discover/'))).flush(found);
    await settle();
  };

  const toDiscovery = async (folder = '/srv/shop', found: Discovery = DISCOVERY): Promise<void> => {
    wizard.folder.set(folder);
    await wizard.advance();
    await discover(found);
  };

  const toCheck = async (): Promise<void> => {
    await toDiscovery();
    await wizard.advance();
    const creating = wizard.advance();
    http.expectOne('/api/applications/').flush(APPLICATION, { status: 201, statusText: 'Created' });
    await creating;
  };

  beforeEach(async () => {
    localStorage.setItem('locale', 'en');
    typed = [];
    jobs = new Subject<Job>();
    prompted = vi.fn(async (_component: Type<unknown>, options: DialogOptions<PasswordPromptData>) => {
      for (const password of typed) {
        if (await options.data?.submit(password)) {
          return true;
        }
      }
      return undefined;
    });
    TestBed.overrideComponent(ApplicationWizardPage, {
      set: {
        providers: [
          {
            provide: Dialogs,
            useValue: {
              open: (component: Type<unknown>, options: DialogOptions<PasswordPromptData>) => ({
                whenClosed: () => prompted(component, options),
              }),
            },
          },
        ],
      },
    });
    TestBed.configureTestingModule({
      providers: [
        { provide: JobWatcher, useValue: { watch: () => jobs } },
        { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter(ROUTES),
      ],
    });
    TestBed.inject(LocaleStore).register({ en, ar });
    http = TestBed.inject(HttpTestingController);
    harness = await RouterTestingHarness.create();
    wizard = await harness.navigateByUrl(`/servers/${SERVER_ID}/applications/new`, ApplicationWizardPage);
    TestBed.tick();
    http.expectOne(`/api/servers/${SERVER_ID}/`).flush(HOST);
    await settle();
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it('walks six steps on the server named in the address, the passphrase optional', async () => {
    expect(html().querySelector('header p')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
      'On the server Production web deploy@web-1.example.com:22',
    );
    const stepper = await TestbedHarnessEnvironment.loader(harness.fixture).getHarness(MatStepperHarness);
    const steps = await stepper.getSteps();

    expect(await Promise.all(steps.map((step) => step.getLabel()))).toEqual([
      'Folder',
      'Discovery',
      'Review',
      'Check',
      'Backup passphrase',
      'Test backup',
    ]);
    expect(await steps[4].isOptional()).toBe(true);
  });

  it('wants a full path for the folder', async () => {
    wizard.folder.set('srv/shop');
    await wizard.advance();

    expect(wizard.step()).toBe(0);
    expect(wizard.error('folder')).toBe('absolute_path_required');
  });

  it('offers the project folders found when no folder was given, and searches the one picked', async () => {
    await toDiscovery('', NO_FOLDER);

    expect(html().textContent).toContain('Choose one of the project folders found on this server');
    expect(html().textContent).not.toContain('is not a folder on this server');
    const pick = await TestbedHarnessEnvironment.loader(harness.fixture).getHarness(
      MatButtonHarness.with({ text: /\/srv\/blog/ }),
    );
    await pick.click();
    const request = await vi.waitFor(() => http.expectOne('/api/applications/discover/'));
    expect(request.request.body).toEqual({ server: SERVER_ID, folder: '/srv/blog' });
    request.flush({ ...DISCOVERY, folder: '/srv/blog' });
    await settle();

    expect(wizard.folder()).toBe('/srv/blog');
  });

  it('says when the folder typed is not on the server', async () => {
    await toDiscovery('/srv/gone', { ...NO_FOLDER, folder: '/srv/gone' });

    expect(html().textContent).toContain('/srv/gone⁩ is not a folder on this server.');
  });

  it('says nothing was run in a folder others can write to', async () => {
    await toDiscovery('/srv/shop', { ...DISCOVERY, trusted: false, candidates: [] });

    expect(html().textContent).toContain('so DBS ran nothing in it');
  });

  it('lists what was found, best first, with what each one has', async () => {
    await toDiscovery();

    const group = await TestbedHarnessEnvironment.loader(harness.fixture).getHarness(MatRadioGroupHarness);
    expect(await group.getCheckedValue()).toBe('0');
    const labels = await Promise.all((await group.getRadioButtons()).map((button) => button.getLabelText()));
    expect(labels).toEqual(['Compose service, Docker web', 'On the server /srv/shop']);
    const page = html().textContent ?? '';
    expect(page).toContain('Replicas: 2');
    expect(page).toContain('django-dbs 0.8.0');
    expect(page).toContain('/srv/shop/backups');
    expect(page).toContain('named in the compose file');
    expect(page).toContain('No Python here can import django-dbs.');
  });

  it('asks for the account password when the server wants it, and searches again with it', async () => {
    typed = ['wrong', 'correct-horse'];
    wizard.folder.set('/srv/shop');
    await wizard.advance();
    const required = { error: { code: 'invalid', message: 'prose', fields: { account_password: ['required'] } } };
    (await vi.waitFor(() => http.expectOne('/api/applications/discover/'))).flush(required, {
      status: 400,
      statusText: 'Bad Request',
    });

    const wrong = await vi.waitFor(() => http.expectOne('/api/applications/discover/'));
    expect(wrong.request.body).toEqual({ server: SERVER_ID, folder: '/srv/shop', account_password: 'wrong' });
    wrong.flush({ error: { code: 'invalid_password', message: 'prose' } }, { status: 400, statusText: 'Bad Request' });
    const right = await vi.waitFor(() => http.expectOne('/api/applications/discover/'));
    expect(right.request.body).toEqual({ server: SERVER_ID, folder: '/srv/shop', account_password: 'correct-horse' });
    right.flush(DISCOVERY);
    await vi.waitFor(() => expect(wizard.discovery()).toEqual(DISCOVERY));

    expect(prompted).toHaveBeenCalledOnce();
    expect(wizard.discoverError()).toBeNull();
  });

  it('fills the review from the chosen candidate and creates the application from it', async () => {
    await toDiscovery();
    wizard.choose(1);
    await wizard.advance();
    expect(wizard.step()).toBe(2);
    expect(wizard.draft()).toMatchObject({ name: 'shop', kind: 'host', python_path: 'python3' });

    wizard.choose(0);
    wizard.back();
    await wizard.advance();
    expect(wizard.draft()).toMatchObject({ kind: 'compose', compose_service: 'web', workdir: '/app' });

    const creating = wizard.advance();
    const post = http.expectOne('/api/applications/');
    expect(post.request.body).toMatchObject({
      server: SERVER_ID,
      discovered: true,
      name: 'shop',
      kind: 'compose',
      engine: 'docker',
      compose_service: 'web',
      project_dir: '/srv/shop',
      env_path: '/srv/shop/.env',
      env_location: 'host',
    });
    post.flush(APPLICATION, { status: 201, statusText: 'Created' });
    await creating;

    expect(wizard.step()).toBe(3);
    http.expectOne(`${DETAIL}check/`).flush(CHECKED);
    await settle();
  });

  it('asks for the account password to add the application, and adds it with it', async () => {
    typed = ['correct-horse'];
    await toDiscovery();
    await wizard.advance();

    const creating = wizard.advance();
    http.expectOne('/api/applications/').flush(
      { error: { code: 'invalid', message: 'prose', fields: { account_password: ['required'] } } },
      { status: 400, statusText: 'Bad Request' },
    );
    const given = await vi.waitFor(() => http.expectOne('/api/applications/'));
    expect(given.request.body).toMatchObject({ server: SERVER_ID, discovered: true, account_password: 'correct-horse' });
    given.flush(APPLICATION, { status: 201, statusText: 'Created' });
    await creating;

    expect(prompted).toHaveBeenCalledOnce();
    expect(prompted.mock.calls[0][1].data?.bodyKey).toBe('applications.wizard.password.adding');
    expect(wizard.step()).toBe(3);
    http.expectOne(`${DETAIL}check/`).flush(CHECKED);
    await settle();
  });

  it('puts what the backend refused under its field and opens the settings behind it', async () => {
    await toDiscovery();
    await wizard.advance();
    expect(wizard.detailsOpen()).toBe(false);

    const creating = wizard.advance();
    http.expectOne('/api/applications/').flush(
      { error: { code: 'invalid', message: 'Server prose', fields: { name: ['name_taken'], container_name: ['invalid'] } } },
      { status: 400, statusText: 'Bad Request' },
    );
    await creating;

    expect(wizard.step()).toBe(2);
    expect(wizard.error('name')).toBe('name_taken');
    expect(wizard.errors()).toMatchObject({ container_name: 'invalid' });
    expect(wizard.detailsOpen()).toBe(true);

    wizard.update('name', 'shop 2');
    expect(wizard.error('name')).toBeNull();
  });

  it('checks on arrival, warns about the panel schedule, and switches to the Python that has django-dbs', async () => {
    const missing: CheckedApplication = {
      ...CHECKED,
      last_check_status: 'problem',
      last_check_report: {
        ...CHECKED.last_check_report,
        dbs_version: null,
        dbs_error: "ModuleNotFoundError: No module named 'dbs'",
        python_suggestion: { python_path: '/app/venv/bin/python', dbs_version: '0.8.0' },
        panel_schedule: { enabled: true, mode: 'thread' },
      },
      remote_version: null,
      installed: false,
      compatible: false,
    };
    await toCheck();
    http.expectOne(`${DETAIL}check/`).flush(missing);
    await settle();

    let page = html().textContent ?? '';
    expect(page).toContain("No module named 'dbs'");
    expect(page).toContain('django-dbs 0.8.0 was found in');
    expect(page).toContain('own DBS panel also schedules backups');

    const nexting = wizard.advance();
    http.expectOne(`${DETAIL}check/`).flush(missing);
    await nexting;
    expect(wizard.step()).toBe(3);

    const switching = wizard.useSuggestedPython();
    const patch = http.expectOne(DETAIL);
    expect(patch.request.body).toEqual({ python_path: '/app/venv/bin/python' });
    patch.flush({ ...APPLICATION, python_path: '/app/venv/bin/python' });
    (await vi.waitFor(() => http.expectOne(`${DETAIL}check/`))).flush(CHECKED);
    await switching;

    page = html().textContent ?? '';
    expect(page).toContain('django-dbs here and in the application work together.');
    await wizard.advance();
    expect(wizard.step()).toBe(4);
  });

  it('locks the steps before the application once it exists', async () => {
    await toCheck();
    http.expectOne(`${DETAIL}check/`).flush(CHECKED);
    await settle();

    wizard.back();
    expect(wizard.step()).toBe(3);
  });

  it('reads the passphrase, takes a test backup and links to the application', async () => {
    await toCheck();
    http.expectOne(`${DETAIL}check/`).flush(CHECKED);
    await settle();
    await wizard.advance();

    wizard.capturePassphrase();
    http.expectOne(`${DETAIL}passphrase/capture/`).flush({ captured: true });
    await settle();
    expect(html().textContent).toContain('The backup passphrase is saved.');
    await wizard.advance();
    expect(wizard.step()).toBe(5);

    wizard.takeBackup();
    http.expectOne('/api/backups/take/').flush({ activity: 7 }, { status: 202, statusText: 'Accepted' });
    jobs.next({
      id: 7,
      action: 'backup.take',
      status: 'running',
      detail: {},
      error_code: '',
      finished_at: null,
      connection: { state: 'alive', last_activity_at: '2026-09-30T12:00:00Z', bytes: 2048 },
    });
    expect(html().querySelector('app-job-connection')).not.toBeNull();

    jobs.next({ id: 7, action: 'backup.take', status: 'succeeded', detail: {}, error_code: '', finished_at: '2026-09-30T12:01:00Z' });
    jobs.complete();
    await settle();
    expect(html().textContent).toContain('The test backup worked.');
    const open = await TestbedHarnessEnvironment.loader(harness.fixture).getHarness(
      MatButtonHarness.with({ text: 'Open the application' }),
    );
    expect(await open.getAppearance()).toBe('filled');
    expect(await (await open.host()).getAttribute('href')).toBe(`/applications/${APPLICATION.id}`);
  });
});
