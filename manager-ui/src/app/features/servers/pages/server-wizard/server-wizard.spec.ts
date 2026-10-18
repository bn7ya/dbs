import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { MatButtonHarness } from '@angular/material/button/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatRadioGroupHarness } from '@angular/material/radio/testing';
import { MatStepperHarness } from '@angular/material/stepper/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import type { Server } from '../../data/servers.types';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { ServerWizardStore } from '../../state/server-wizard.store';
import { SERVER } from '../../testing/servers.fixtures';
import { ServerWizardPage } from './server-wizard';

const HOST_KEY = { key_type: 'ssh-ed25519', line: 'web-1 ssh-ed25519 AAAA', fingerprint: 'SHA256:abc' };

const CHECKED: Server = {
  ...SERVER,
  last_check_report: {
    system: 'Linux 6.8.0',
    engines: {
      docker: { installed: true, usable: false, version: null, compose: null, error: 'engine_permission_denied' },
      podman: { installed: true, usable: true, version: '5.2.2', compose: null, error: '' },
    },
    timeout: false,
  },
};

describe('ServerWizardPage', () => {
  let http: HttpTestingController;
  let fixture: ComponentFixture<ServerWizardPage>;
  let wizard: ServerWizardPage;

  const html = (): HTMLElement => {
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  };

  const address = async (): Promise<void> => {
    wizard.update('name', 'Production web');
    wizard.update('host', 'web-1.example.com');
    wizard.update('username', 'deploy');
    await wizard.advance();
  };

  const hostKey = async (): Promise<void> => {
    await address();
    http.expectOne('/api/servers/fingerprint/').flush(HOST_KEY);
    await fixture.whenStable();
    wizard.hostKeyConfirmed.set(true);
    await wizard.advance();
  };

  const createWithPassword = async (): Promise<void> => {
    await hostKey();
    wizard.setSignIn('password');
    wizard.update('password', 'secret');
    const creating = wizard.advance();
    http.expectOne('/api/servers/').flush(SERVER, { status: 201, statusText: 'Created' });
    await creating;
  };

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [
        ServerWizardStore,
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

  it('walks five steps from the address to the applications', async () => {
    html();
    const stepper = await TestbedHarnessEnvironment.loader(fixture).getHarness(MatStepperHarness);
    const steps = await stepper.getSteps();

    expect(await Promise.all(steps.map((step) => step.getLabel()))).toEqual([
      'Address',
      'Host key',
      'Sign-in',
      'Check',
      'Applications',
    ]);
  });

  it('holds the address until it is complete, then reads the host key on arrival', async () => {
    await wizard.advance();
    expect(wizard.step()).toBe(0);
    expect(wizard.error('name')).toBe('required');

    wizard.update('port', 70000);
    await address();
    expect(wizard.step()).toBe(0);
    expect(wizard.error('port')).toBe('port_range');

    wizard.update('port', 2222);
    await wizard.advance();
    expect(wizard.step()).toBe(1);
    const request = http.expectOne('/api/servers/fingerprint/');
    expect(request.request.body).toEqual({ host: 'web-1.example.com', port: 2222 });
    request.flush(HOST_KEY);
    await fixture.whenStable();

    const page = html().textContent ?? '';
    expect(page).toContain('SHA256:abc');
    expect(page).toContain('ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub');
  });

  it('wants the fingerprints compared, and forgets the key when the address changes', async () => {
    await address();
    http.expectOne('/api/servers/fingerprint/').flush(HOST_KEY);
    await fixture.whenStable();

    await wizard.advance();
    expect(wizard.step()).toBe(1);
    expect(wizard.error('host_key')).toBe('host_key_unconfirmed');

    wizard.update('host', 'web-2.example.com');
    expect(wizard.hostKey()).toBeNull();
    expect(wizard.error('host_key')).toBe('host_key_missing');
  });

  it('creates the server with a generated key and shows the line to add before the check', async () => {
    await hostKey();
    expect(wizard.step()).toBe(2);
    html();
    const signIn = await TestbedHarnessEnvironment.loader(fixture).getHarness(MatRadioGroupHarness);
    expect(await signIn.getCheckedValue()).toBe('generate');

    const creating = wizard.advance();
    const post = http.expectOne('/api/servers/');
    expect(post.request.body).toEqual({
      name: 'Production web',
      host: 'web-1.example.com',
      port: 22,
      username: 'deploy',
      auth_method: 'key',
      generate_key: true,
      host_key: HOST_KEY.line,
    });
    post.flush(
      { ...SERVER, public_key: 'ssh-ed25519 AAAA dbs', authorized_keys_hint: 'ssh-ed25519 AAAA dbs' },
      { status: 201, statusText: 'Created' },
    );
    await creating;

    expect(wizard.step()).toBe(2);
    expect(html().textContent).toContain('~deploy/.ssh/authorized_keys');

    await wizard.advance();
    expect(wizard.step()).toBe(3);
    http.expectOne(`/api/servers/${SERVER.id}/check/`).flush(CHECKED);
    await fixture.whenStable();
  });

  it('sends a pasted key and takes the developer back to the field the backend refused', async () => {
    await hostKey();
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

    expect(wizard.step()).toBe(0);
    expect(wizard.error('name')).toBe('name_taken');
  });

  it('checks the server on arrival and shows the engines it has', async () => {
    await createWithPassword();
    expect(wizard.step()).toBe(3);
    http.expectOne(`/api/servers/${SERVER.id}/check/`).flush(CHECKED);
    await fixture.whenStable();

    const page = html().textContent ?? '';
    expect(page).toContain('Linux 6.8.0');
    expect(page).toContain('Installed, but the SSH user may not use it');
    expect(page).toContain('Add the user to the engine');
    expect(page).toContain('5.2.2');
    expect(page).toContain('No Compose');
    expect(page).toContain('The manager can sign in to this server.');
  });

  it('says to add the generated key when the server refuses it, and checks again on Next', async () => {
    await hostKey();
    const creating = wizard.advance();
    http
      .expectOne('/api/servers/')
      .flush({ ...SERVER, public_key: 'ssh-ed25519 AAAA dbs' }, { status: 201, statusText: 'Created' });
    await creating;
    await wizard.advance();
    http
      .expectOne(`/api/servers/${SERVER.id}/check/`)
      .flush({ error: { code: 'ssh_auth_failed', message: 'Server prose' } }, { status: 400, statusText: 'Bad Request' });
    await fixture.whenStable();

    expect(html().textContent).toContain('The server refused the new key.');

    const again = wizard.advance();
    http.expectOne(`/api/servers/${SERVER.id}/check/`).flush(CHECKED);
    await again;
    expect(wizard.step()).toBe(3);

    await wizard.advance();
    expect(wizard.step()).toBe(4);
  });

  it('ends on adding an application to the new server', async () => {
    await createWithPassword();
    http.expectOne(`/api/servers/${SERVER.id}/check/`).flush(CHECKED);
    await fixture.whenStable();
    await wizard.advance();
    expect(wizard.step()).toBe(4);
    await fixture.whenStable();

    const add = await TestbedHarnessEnvironment.loader(fixture).getHarness(
      MatButtonHarness.with({ text: /Add an application/ }),
    );
    expect(await add.getAppearance()).toBe('filled');
    expect(await (await add.host()).getAttribute('href')).toBe(`/servers/${SERVER.id}/applications/new`);
  });
});
