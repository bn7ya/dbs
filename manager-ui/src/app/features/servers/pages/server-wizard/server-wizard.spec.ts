import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import type { Type } from '@angular/core';
import { MatRadioGroupHarness } from '@angular/material/radio/testing';
import { MatStepperHarness } from '@angular/material/stepper/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import { JobWatcher } from '@core/jobs/job-watcher';
import type { Job } from '@core/jobs/job.types';
import { Dialogs } from '@shared/dialogs/dialogs';
import type { DialogOptions } from '@shared/dialogs/dialogs.types';
import type { PasswordPromptData } from '@shared/password-prompt/password-prompt.types';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import type { Discovery } from '../../data/servers.types';
import { ServerWizardStore } from '../../state/server-wizard.store';
import { SERVER } from '../../testing/servers.fixtures';
import { ServerWizardPage } from './server-wizard';

const HOST_KEY = { key_type: 'ssh-ed25519', line: 'web-1 ssh-ed25519 AAAA', fingerprint: 'SHA256:abc' };

const SNIPPET = JSON.stringify({
  dbs_connection: 1,
  hostname: 'web-1.example.com',
  ssh_user: 'deploy',
  project_dir: '/srv/app',
  python_path: '/srv/app/.venv/bin/python',
  manage_path: 'manage.py',
  settings_module: 'app.settings',
  remote_backup_dir: '/var/backups/dbs',
  file_roots: ['/srv/app/media'],
  env_path: '/srv/app/.env',
  dbs_version: '0.5.0',
  host_keys: [{ type: 'ssh-ed25519', fingerprint: 'SHA256:abc' }],
});

const DISCOVERY: Discovery = {
  project_dir: '/srv/app',
  python_path: '/srv/app/.venv/bin/python',
  manage_path: 'manage.py',
  settings_module: 'app.settings',
  remote_backup_dir: '/var/backups/dbs',
  file_roots: [],
  env_path: '/srv/app/.env',
  dbs_version: '0.5.0',
  is_project: true,
  candidates: { project_dirs: ['/srv/app', '/srv/blog'], python_paths: ['/srv/app/.venv/bin/python', 'python3', 'python'] },
};

const DONE: Job = { id: 1, action: 'backup.take', status: 'succeeded', detail: {}, error_code: '', finished_at: null };

describe('ServerWizardPage', () => {
  let http: HttpTestingController;
  let fixture: ComponentFixture<ServerWizardPage>;
  let wizard: ServerWizardPage;
  let typed: string[];
  let prompted: Mock<(component: Type<unknown>, options: DialogOptions<PasswordPromptData>) => Promise<true | undefined>>;

  const html = (): HTMLElement => {
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  };

  const connect = async (): Promise<void> => {
    wizard.snippetText.set(SNIPPET);
    await wizard.advance();
    const fetching = wizard.fetchHostKey();
    http.expectOne('/api/servers/fingerprint/').flush(HOST_KEY);
    await fetching;
    wizard.hostKeyConfirmed.set(true);
    await wizard.advance();
  };

  const createWithPassword = async (): Promise<void> => {
    await connect();
    wizard.setSignIn('password');
    wizard.update('password', 'secret');
    const creating = wizard.advance();
    http.expectOne('/api/servers/').flush(SERVER, { status: 201, statusText: 'Created' });
    await creating;
  };

  const answerDiscovery = async (found: Discovery = DISCOVERY): Promise<void> => {
    http.expectOne(`/api/servers/${SERVER.id}/discover/`).flush(found);
    await fixture.whenStable();
  };

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    typed = [];
    prompted = vi.fn(async (_component: Type<unknown>, options: DialogOptions<PasswordPromptData>) => {
      for (const password of typed) {
        if (await options.data?.submit(password)) {
          return true;
        }
      }
      return undefined;
    });
    TestBed.overrideComponent(ServerWizardPage, {
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
        ServerWizardStore,
        { provide: JobWatcher, useValue: { watch: () => of(DONE) } },
        { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    TestBed.inject(LocaleStore).register({ en, ar });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(ServerWizardPage);
    wizard = fixture.componentInstance;
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it('walks seven steps, the snippet and the passphrase optional', async () => {
    html();
    const stepper = await TestbedHarnessEnvironment.loader(fixture).getHarness(MatStepperHarness);
    const steps = await stepper.getSteps();

    expect(await Promise.all(steps.map((step) => step.getLabel()))).toEqual([
      'Connection snippet',
      'Address and host key',
      'Sign-in',
      'Project',
      'Check',
      'Backup passphrase',
      'Test backup',
    ]);
    expect(await steps[0].isOptional()).toBe(true);
    expect(await steps[5].isOptional()).toBe(true);
  });

  it('names a snippet that is not JSON and holds the reader on its step', async () => {
    wizard.snippetText.set('{nope');
    await wizard.advance();

    expect(wizard.step()).toBe(0);
    expect(html().querySelector('mat-error')?.textContent?.trim()).toBe('This is not valid JSON. Paste the whole snippet.');
  });

  it('fills the connection from the snippet and compares the fetched fingerprint with it', async () => {
    wizard.snippetText.set(SNIPPET);
    await wizard.advance();

    expect(wizard.step()).toBe(1);
    expect(wizard.draft()).toMatchObject({ name: 'web-1.example.com', host: 'web-1.example.com', username: 'deploy' });
    expect(wizard.draft().file_roots).toEqual(['/srv/app/media']);

    await wizard.advance();
    expect(wizard.error('host_key')).toBe('host_key_missing');

    const fetching = wizard.fetchHostKey();
    const request = http.expectOne('/api/servers/fingerprint/');
    expect(request.request.body).toEqual({ host: 'web-1.example.com', port: 22 });
    request.flush(HOST_KEY);
    await fetching;
    expect(html().textContent).toContain('Matches the snippet');

    wizard.update('port', 2222);
    expect(wizard.hostKey()).toBeNull();
  });

  it('creates the server with a generated key and shows the line to add before going on', async () => {
    await connect();
    expect(wizard.step()).toBe(2);
    html();
    const signIn = await TestbedHarnessEnvironment.loader(fixture).getHarness(MatRadioGroupHarness);
    expect(await signIn.getCheckedValue()).toBe('generate');

    const creating = wizard.advance();
    const post = http.expectOne('/api/servers/');
    expect(post.request.body).toMatchObject({
      name: 'web-1.example.com',
      auth_method: 'key',
      generate_key: true,
      host_key: HOST_KEY.line,
      project_dir: '/srv/app',
    });
    expect(post.request.body).not.toHaveProperty('private_key');
    post.flush(
      { ...SERVER, public_key: 'ssh-ed25519 AAAA dbs', authorized_keys_hint: 'ssh-ed25519 AAAA dbs' },
      { status: 201, statusText: 'Created' },
    );
    await creating;

    expect(wizard.step()).toBe(2);
    expect(html().textContent).toContain('~deploy/.ssh/authorized_keys');

    await wizard.advance();
    expect(wizard.step()).toBe(3);
    const discovery = http.expectOne(`/api/servers/${SERVER.id}/discover/`);
    expect(discovery.request.body).toEqual({ project_dir: '/srv/app' });
    discovery.flush(DISCOVERY);
  });

  it('sends a pasted key and puts what the backend refused under its field', async () => {
    await connect();
    wizard.setSignIn('key');
    await wizard.advance();
    expect(wizard.error('private_key')).toBe('required');
    wizard.update('private_key', '-----BEGIN OPENSSH PRIVATE KEY-----');

    const creating = wizard.advance();
    const post = http.expectOne('/api/servers/');
    expect(post.request.body).toMatchObject({ auth_method: 'key', private_key: '-----BEGIN OPENSSH PRIVATE KEY-----' });
    post.flush(
      { error: { code: 'invalid', message: 'Server prose', fields: { name: ['name_taken'] } } },
      { status: 400, statusText: 'Bad Request' },
    );
    await creating;

    expect(wizard.step()).toBe(2);
    expect(wizard.error('name')).toBe('name_taken');
  });

  it('finds the project on its own and fills what it found', async () => {
    await createWithPassword();
    expect(wizard.step()).toBe(3);
    await answerDiscovery();

    expect(wizard.projects()).toEqual(['/srv/app', '/srv/blog']);
    expect(wizard.draft()).toMatchObject({
      project_dir: '/srv/app',
      python_path: '/srv/app/.venv/bin/python',
      settings_module: 'app.settings',
      env_path: '/srv/app/.env',
    });
    expect(html().textContent).toContain('Ready: django-dbs 0.5.0 was found for this project.');

    wizard.chooseProject('/srv/blog');
    const chosen = http.expectOne(`/api/servers/${SERVER.id}/discover/`);
    expect(chosen.request.body).toEqual({ project_dir: '/srv/blog' });
    expect(html().textContent).not.toContain('Ready: django-dbs');
    await wizard.advance();
    expect(wizard.step()).toBe(3);
    http.expectNone(`/api/servers/${SERVER.id}/`);
    chosen.flush({
      ...DISCOVERY,
      project_dir: '/srv/blog',
      python_path: 'python3',
      settings_module: '',
      env_path: '',
      dbs_version: null,
      candidates: { project_dirs: ['/srv/blog'], python_paths: ['python3', 'python'] },
    });
    await fixture.whenStable();

    expect(wizard.projects()).toEqual(['/srv/app', '/srv/blog']);
    expect(wizard.draft()).toMatchObject({ project_dir: '/srv/blog', python_path: 'python3', settings_module: '', env_path: '' });
    expect(html().textContent).toContain('no Python on the server could import django-dbs');

    wizard.update('project_dir', '/srv/elsewhere');
    expect(html().textContent).not.toContain('no Python on the server could import django-dbs');
  });

  it('asks for the account password when the server wants it, and keeps asking after a wrong one', async () => {
    await createWithPassword();
    typed = ['wrong', 'correct-horse'];
    const required = { error: { code: 'invalid', message: 'prose', fields: { account_password: ['required'] } } };
    http.expectOne(`/api/servers/${SERVER.id}/discover/`).flush(required, { status: 400, statusText: 'Bad Request' });

    const wrong = await vi.waitFor(() => http.expectOne(`/api/servers/${SERVER.id}/discover/`));
    expect(wrong.request.body).toEqual({ project_dir: '/srv/app', account_password: 'wrong' });
    wrong.flush({ error: { code: 'invalid_password', message: 'prose' } }, { status: 400, statusText: 'Bad Request' });
    const right = await vi.waitFor(() => http.expectOne(`/api/servers/${SERVER.id}/discover/`));
    expect(right.request.body).toEqual({ project_dir: '/srv/app', account_password: 'correct-horse' });
    right.flush(DISCOVERY);
    await vi.waitFor(() => expect(wizard.discovery()).toEqual(DISCOVERY));

    expect(prompted).toHaveBeenCalledOnce();
    expect(prompted.mock.calls[0][1]).toMatchObject({ titleKey: 'servers.wizard.password.title' });
    expect(wizard.discoverError()).toBeNull();
  });

  it('keeps a Python from the snippet when the search could not prove another one', async () => {
    await createWithPassword();
    await answerDiscovery({ ...DISCOVERY, python_path: 'python3', dbs_version: null });

    expect(wizard.draft().python_path).toBe('/srv/app/.venv/bin/python');
  });

  it('says django-dbs was not found and switches to the Python that has it', async () => {
    await createWithPassword();
    await answerDiscovery();
    const saving = wizard.advance();
    http.expectOne(`/api/servers/${SERVER.id}/`).flush(SERVER);
    await saving;
    expect(wizard.step()).toBe(4);

    http.expectOne(`/api/servers/${SERVER.id}/check/`).flush({
      ...SERVER,
      python_path: 'python3',
      last_check_report: {
        dbs_version: null,
        dbs_error: "ModuleNotFoundError: No module named 'dbs'",
        python_suggestion: { python_path: '/srv/app/venv/bin/python', dbs_version: '0.5.0' },
      },
      local_version: '0.5.0',
      remote_version: null,
      installed: false,
      compatible: false,
      last_health: null,
    });
    await fixture.whenStable();
    const page = html().textContent ?? '';
    expect(page).toContain('django-dbs was not found with');
    expect(page).toContain("No module named 'dbs'");
    expect(page).toContain('django-dbs 0.5.0 was found in');
    expect(page).not.toContain('does not work with this manager');

    const switching = wizard.useSuggestedPython();
    const patch = http.expectOne(`/api/servers/${SERVER.id}/`);
    expect(patch.request.method).toBe('PATCH');
    expect(patch.request.body).toEqual({ python_path: '/srv/app/venv/bin/python' });
    patch.flush({ ...SERVER, python_path: '/srv/app/venv/bin/python' });
    await fixture.whenStable();
    http
      .expectOne(`/api/servers/${SERVER.id}/check/`)
      .flush({ ...SERVER, local_version: '0.5.0', remote_version: '0.5.0', installed: true, compatible: true, last_health: null });
    await switching;

    expect(wizard.draft().python_path).toBe('/srv/app/venv/bin/python');
    expect(html().textContent).toContain('The two versions work together.');

    wizard.chooseProjectAgain();
    expect(wizard.step()).toBe(3);
  });

  it('warns about an old django-dbs, refuses an incompatible one, and finishes with a test backup', async () => {
    await createWithPassword();
    expect(wizard.step()).toBe(3);
    await answerDiscovery();

    const saving = wizard.advance();
    http.expectOne(`/api/servers/${SERVER.id}/`).flush(SERVER);
    await saving;
    expect(wizard.step()).toBe(4);

    http
      .expectOne(`/api/servers/${SERVER.id}/check/`)
      .flush({ ...SERVER, local_version: '0.5.0', remote_version: '0.2.0', installed: true, compatible: false, last_health: null });
    await fixture.whenStable();
    expect(html().textContent).toContain('does not work with this manager');
    const rechecking = wizard.advance();
    http
      .expectOne(`/api/servers/${SERVER.id}/check/`)
      .flush({ ...SERVER, local_version: '0.5.0', remote_version: '0.4.2', installed: true, compatible: true, last_health: null });
    await rechecking;
    expect(html().textContent).toContain('older than 0.5.0');
    await wizard.advance();
    expect(wizard.step()).toBe(5);
    await wizard.advance();
    expect(wizard.step()).toBe(6);

    wizard.takeBackup();
    http.expectOne('/api/backups/take/').flush({ activity: 1 }, { status: 202, statusText: 'Accepted' });
    const page = html();
    expect(page.textContent).toContain('The test backup worked.');
    expect(page.querySelector(`a[href="/servers/${SERVER.id}/backups"]`)).not.toBeNull();
  });
});
