import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatRadioGroupHarness } from '@angular/material/radio/testing';
import { MatStepperHarness } from '@angular/material/stepper/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import { JobWatcher } from '@core/jobs/job-watcher';
import type { Job } from '@core/jobs/job.types';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
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

const DONE: Job = { id: 1, action: 'backup.take', status: 'succeeded', detail: {}, error_code: '', finished_at: null };

describe('ServerWizardPage', () => {
  let http: HttpTestingController;
  let fixture: ComponentFixture<ServerWizardPage>;
  let wizard: ServerWizardPage;

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

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
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

  it('warns about an old django-dbs, refuses an incompatible one, and finishes with a test backup', async () => {
    await connect();
    wizard.setSignIn('password');
    wizard.update('password', 'secret');
    const creating = wizard.advance();
    http.expectOne('/api/servers/').flush(SERVER, { status: 201, statusText: 'Created' });
    await creating;
    expect(wizard.step()).toBe(3);

    const saving = wizard.advance();
    http.expectOne(`/api/servers/${SERVER.id}/`).flush(SERVER);
    await saving;
    expect(wizard.step()).toBe(4);

    const refusing = wizard.advance();
    http
      .expectOne(`/api/servers/${SERVER.id}/check/`)
      .flush({ ...SERVER, local_version: '0.5.0', remote_version: '0.3.0', compatible: false, last_health: null });
    await refusing;
    expect(html().textContent).toContain('does not work with this manager');
    const rechecking = wizard.advance();
    http
      .expectOne(`/api/servers/${SERVER.id}/check/`)
      .flush({ ...SERVER, local_version: '0.5.0', remote_version: '0.4.2', compatible: true, last_health: null });
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
