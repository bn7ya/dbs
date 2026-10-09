import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { JobWatcher } from '@core/jobs/job-watcher';
import type { Job } from '@core/jobs/job.types';
import { CREATE, SERVER } from '../testing/servers.fixtures';
import { ServerWizardStore } from './server-wizard.store';

const DONE: Job = { id: 1, action: 'backup.take', status: 'succeeded', detail: {}, error_code: '', finished_at: null };

describe('ServerWizardStore', () => {
  let store: ServerWizardStore;
  let http: HttpTestingController;
  const watch = vi.fn(() => of(DONE));

  const created = async (extra: Record<string, unknown> = {}): Promise<void> => {
    const creating = store.create(CREATE);
    http.expectOne('/api/servers/').flush({ ...SERVER, ...extra }, { status: 201, statusText: 'Created' });
    await creating;
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        ServerWizardStore,
        { provide: JobWatcher, useValue: { watch } },
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    store = TestBed.inject(ServerWizardStore);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    watch.mockClear();
  });

  it('creates the server once and keeps the generated public key', async () => {
    await created({ public_key: 'ssh-ed25519 AAAA dbs', authorized_keys_hint: 'echo ... >> authorized_keys' });

    expect(store.server()?.id).toBe(SERVER.id);
    expect(store.publicKey()).toBe('ssh-ed25519 AAAA dbs');

    const reading = store.rereadPublicKey();
    http.expectOne(`/api/servers/${SERVER.id}/public-key/`).flush({ public_key: 'ssh-ed25519 BBBB dbs' });
    await reading;
    expect(store.publicKey()).toBe('ssh-ed25519 BBBB dbs');
  });

  it('keeps the field codes when the backend refuses the server', async () => {
    const creating = store.create(CREATE);
    http.expectOne('/api/servers/').flush(
      { error: { code: 'invalid', message: 'Server prose', fields: { name: ['name_taken'] } } },
      { status: 400, statusText: 'Bad Request' },
    );

    await expect(creating).resolves.toBeNull();
    expect(store.createError()?.fields?.['name']).toEqual(['name_taken']);
    expect(store.server()).toBeNull();
  });

  it('discovers the project, saves it without the account password and runs the check', async () => {
    await created();

    const discovering = store.discover();
    http.expectOne(`/api/servers/${SERVER.id}/discover/`).flush({ project_dir: '/srv/app' });
    expect((await discovering)?.project_dir).toBe('/srv/app');

    const settings = {
      project_dir: '/srv/app',
      python_path: 'python3',
      manage_path: 'manage.py',
      settings_module: '',
      remote_backup_dir: '/var/backups/dbs',
      file_roots: [],
      env_path: '',
    };
    const saving = store.saveProject(settings);
    const patch = http.expectOne(`/api/servers/${SERVER.id}/`);
    expect(patch.request.method).toBe('PATCH');
    expect(patch.request.body).toEqual(settings);
    patch.flush({ ...SERVER, project_dir: '/srv/app' });
    await expect(saving).resolves.toBe(true);

    const checking = store.check();
    http
      .expectOne(`/api/servers/${SERVER.id}/check/`)
      .flush({ ...SERVER, local_version: '0.5.0', remote_version: '0.5.0', compatible: true, last_health: null });
    await checking;
    expect(store.checked()?.compatible).toBe(true);
  });

  it('captures the passphrase and follows the test backup to its end', async () => {
    await created();

    const capturing = store.capturePassphrase();
    http.expectOne(`/api/servers/${SERVER.id}/passphrase/capture/`).flush({ captured: true });
    await capturing;
    expect(store.captured()).toBe(true);

    store.takeBackup();
    const take = http.expectOne('/api/backups/take/');
    expect(take.request.body).toEqual({ server: SERVER.id });
    take.flush({ activity: 1 }, { status: 202, statusText: 'Accepted' });

    expect(watch).toHaveBeenCalledWith(1);
    expect(store.backupJob()?.status).toBe('succeeded');
    expect(store.backingUp()).toBe(false);
  });
});
