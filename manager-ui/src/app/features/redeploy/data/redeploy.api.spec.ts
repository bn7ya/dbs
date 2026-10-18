import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  APPLICATIONS,
  BACKUPS,
  COMPOSE_APPLICATION,
  DEPLOY_ID,
  ENV_VERSIONS,
  MIGRATE,
  PULL,
  SOURCE,
  TARGET,
  pageOf,
} from '../testing/redeploy.fixtures';
import { RedeployApi } from './redeploy.api';

describe('RedeployApi', () => {
  let api: RedeployApi;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(RedeployApi);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
  });

  it('reads one application, its deploy steps with it', async () => {
    const reading = firstValueFrom(api.application(SOURCE));
    const request = http.expectOne(`/api/applications/${SOURCE}/`);
    expect(request.request.method).toBe('GET');
    request.flush(COMPOSE_APPLICATION);

    await expect(reading).resolves.toEqual(COMPOSE_APPLICATION);
  });

  it('lists the first page of every application, of the backups and of the .env versions of one', () => {
    void firstValueFrom(api.applications());
    void firstValueFrom(api.backups(SOURCE));
    void firstValueFrom(api.envVersions(SOURCE));

    http.expectOne('/api/applications/?page=1&page_size=100').flush(pageOf(APPLICATIONS));
    http.expectOne(`/api/backups/?page=1&page_size=100&application=${SOURCE}`).flush(pageOf(BACKUPS));
    http.expectOne(`/api/envfiles/?page=1&page_size=100&application=${SOURCE}`).flush(pageOf(ENV_VERSIONS));
  });

  it('saves the deploy steps with the account password', async () => {
    const saving = firstValueFrom(api.saveSteps(SOURCE, { steps: [PULL, MIGRATE], account_password: 'hunter2' }));
    const request = http.expectOne(`/api/applications/${SOURCE}/deploy-steps/`);
    expect(request.request.method).toBe('PUT');
    expect(request.request.body).toEqual({ steps: [PULL, MIGRATE], account_password: 'hunter2' });
    request.flush({ ...COMPOSE_APPLICATION, deploy_steps: [PULL, MIGRATE] });

    await expect(saving).resolves.toMatchObject({ deploy_steps: [PULL, MIGRATE] });
  });

  it('starts a deploy in place, a move and a revert, each answering with the job to follow', async () => {
    const run = { rehearsal: true, password: '', confirm_name: '' };
    const deploying = firstValueFrom(api.deploy(SOURCE, run));
    const deploy = http.expectOne(`/api/applications/${SOURCE}/deploy/`);
    expect(deploy.request.method).toBe('POST');
    expect(deploy.request.body).toEqual(run);
    deploy.flush({ activity: DEPLOY_ID }, { status: 202, statusText: 'Accepted' });
    await expect(deploying).resolves.toEqual({ activity: DEPLOY_ID });

    const move = {
      ...run,
      source_application: SOURCE,
      target_application: TARGET,
      backup: null,
      env_version: null,
      flush: false,
    };
    void firstValueFrom(api.move(move));
    const moved = http.expectOne('/api/redeploy/');
    expect(moved.request.method).toBe('POST');
    expect(moved.request.body).toEqual(move);
    moved.flush({ activity: 9 }, { status: 202, statusText: 'Accepted' });

    void firstValueFrom(api.revert(DEPLOY_ID, { rehearsal: false, password: 'hunter2', confirm_name: 'Shop' }));
    const revert = http.expectOne(`/api/redeploy/${DEPLOY_ID}/revert/`);
    expect(revert.request.method).toBe('POST');
    expect(revert.request.body).toEqual({ rehearsal: false, password: 'hunter2', confirm_name: 'Shop' });
    revert.flush({ activity: 10 }, { status: 202, statusText: 'Accepted' });
  });
});
