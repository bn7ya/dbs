import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, type TestRequest } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import { JobWatcher } from '@core/jobs/job-watcher';
import type { Job } from '@core/jobs/job.types';
import { Toaster } from '@shared/toaster/toaster';
import type { ToastMessage } from '@shared/toaster/toaster.types';
import ar from '../i18n/ar.json';
import en from '../i18n/en.json';
import {
  COMPOSE_APPLICATION,
  DEPLOYED,
  DEPLOY_ID,
  DEPLOY_STOPPED,
  MIGRATE,
  PULL,
  REVERTED,
  REVERT_ID,
  SOURCE,
} from '../testing/redeploy.fixtures';
import { DeployStore } from './deploy.store';

const REHEARSAL = { rehearsal: true, password: '', confirm_name: '' };
const FOR_REAL = { rehearsal: false, password: 'hunter2', confirm_name: 'Shop' };

describe('DeployStore', () => {
  let store: DeployStore;
  let http: HttpTestingController;
  let toasts: MockInstance<(message: ToastMessage) => void>;
  let watched: Map<number, Job>;

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const open = async (): Promise<void> => {
    store.open(SOURCE);
    TestBed.tick();
    http.expectOne(`/api/applications/${SOURCE}/`).flush(COMPOSE_APPLICATION);
    await settle();
  };

  const stepsRequest = (): TestRequest => http.expectOne(`/api/applications/${SOURCE}/deploy-steps/`);

  const refuse = (request: TestRequest, code: string, fields?: Record<string, string[]>): void =>
    request.flush(
      { error: { code, message: 'Server prose', ...(fields === undefined ? {} : { fields }) } },
      { status: 400, statusText: 'Bad Request' },
    );

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    watched = new Map();
    TestBed.configureTestingModule({
      providers: [
        DeployStore,
        { provide: JobWatcher, useValue: { watch: (id: number) => of(watched.get(id)) } },
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    TestBed.inject(LocaleStore).register({ en, ar });
    toasts = vi.spyOn(TestBed.inject(Toaster), 'add').mockReturnValue(undefined);
    store = TestBed.inject(DeployStore);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('reads nothing until the page opens an application, then its deploy steps', async () => {
    TestBed.tick();
    http.expectNone(() => true);
    expect(store.application()).toBeNull();

    await open();

    expect(store.application()).toEqual(COMPOSE_APPLICATION);
  });

  it('says why the application could not be read, and reads it again', async () => {
    store.open(SOURCE);
    TestBed.tick();
    http
      .expectOne(`/api/applications/${SOURCE}/`)
      .flush({ error: { code: 'not_found', message: 'Server prose' } }, { status: 404, statusText: 'Not Found' });
    await settle();
    expect(store.loadError()?.code).toBe('not_found');

    store.reload();
    TestBed.tick();
    http.expectOne(`/api/applications/${SOURCE}/`).flush(COMPOSE_APPLICATION);
    await settle();
    expect(store.loadError()).toBeNull();
  });

  describe('saving the steps', () => {
    it('sends them with the password, keeps what the manager answers, and says so', async () => {
      await open();

      const saving = store.saveSteps([PULL, MIGRATE], 'hunter2');
      expect(store.saving()).toBe(true);
      const request = stepsRequest();
      expect(request.request.method).toBe('PUT');
      expect(request.request.body).toEqual({ steps: [PULL, MIGRATE], account_password: 'hunter2' });
      request.flush({ ...COMPOSE_APPLICATION, deploy_steps: [PULL, MIGRATE] });

      await expect(saving).resolves.toBe(true);
      expect(store.saving()).toBe(false);
      expect(store.application()?.deploy_steps).toEqual([PULL, MIGRATE]);
      expect(toasts).toHaveBeenCalledWith({ severity: 'success', summary: 'Deploy steps saved.' });
      TestBed.tick();
      http.expectNone(`/api/applications/${SOURCE}/`);
    });

    it('reads a refusal of the steps themselves, row by row', async () => {
      await open();

      const saving = store.saveSteps([PULL, MIGRATE], 'hunter2');
      refuse(stepsRequest(), 'invalid', { 'steps.1': ['compose_required', 'invalid_timeout'], steps: ['too_many_steps'] });

      await expect(saving).resolves.toBe(false);
      expect(store.stepErrors()).toEqual(new Map([[1, ['compose_required', 'invalid_timeout']]]));
      expect(store.listErrors()).toEqual(['too_many_steps']);
      expect(store.stepsRefused()).toBe(true);
      expect(store.application()?.deploy_steps).toEqual(COMPOSE_APPLICATION.deploy_steps);

      store.clearSaveError();
      expect(store.stepErrors().size).toBe(0);
      expect(store.stepsRefused()).toBe(false);
    });

    it('keeps a wrong password for the prompt to say', async () => {
      await open();

      const saving = store.saveSteps([PULL], 'wrong');
      refuse(stepsRequest(), 'invalid_password');

      await expect(saving).resolves.toBe(false);
      expect(store.saveError()?.code).toBe('invalid_password');
      expect(store.stepsRefused()).toBe(false);
      expect(toasts).not.toHaveBeenCalled();
    });
  });

  describe('deploying', () => {
    it('rehearses, follows the job to its end, and reads what it changed', async () => {
      watched.set(DEPLOY_ID, { ...DEPLOYED, detail: { ...DEPLOYED.detail, rehearsal: true } });
      await open();

      store.deploy(REHEARSAL);
      const request = http.expectOne(`/api/applications/${SOURCE}/deploy/`);
      expect(request.request.body).toEqual(REHEARSAL);
      expect(store.deploying.busy()).toBe(true);
      expect(store.deploying.rehearsal()).toBe(true);
      request.flush({ activity: DEPLOY_ID }, { status: 202, statusText: 'Accepted' });

      expect(store.deploying.busy()).toBe(false);
      expect(store.deploying.job()?.status).toBe('succeeded');
      expect(store.outcome().after).toEqual({ git_head: 'f6e5d4c3b2a1', image: 'sha256:fedcba9876543210' });
      expect(store.outcome().revertable).toBe(false);
    });

    it('holds a refusal as an ApiError, and forgets it when asked', async () => {
      await open();

      store.deploy(FOR_REAL);
      http
        .expectOne(`/api/applications/${SOURCE}/deploy/`)
        .flush({ error: { code: 'no_deploy_steps', message: 'Server prose' } }, { status: 409, statusText: 'Conflict' });

      expect(store.deploying.error()?.code).toBe('no_deploy_steps');
      expect(store.deploying.busy()).toBe(false);
      store.deploying.clearError();
      expect(store.deploying.error()).toBeNull();
    });

    it('restores the safety backup of a deploy that stopped, and forgets that restore on the next deploy', async () => {
      watched.set(DEPLOY_ID, DEPLOY_STOPPED).set(REVERT_ID, REVERTED);
      await open();
      store.revert(FOR_REAL);
      http.expectNone(() => true);

      store.deploy(FOR_REAL);
      http.expectOne(`/api/applications/${SOURCE}/deploy/`).flush({ activity: DEPLOY_ID }, { status: 202, statusText: 'Accepted' });
      expect(store.outcome().revertable).toBe(true);

      store.revert(FOR_REAL);
      const revert = http.expectOne(`/api/redeploy/${DEPLOY_ID}/revert/`);
      expect(revert.request.body).toEqual(FOR_REAL);
      revert.flush({ activity: REVERT_ID }, { status: 202, statusText: 'Accepted' });
      expect(store.reverting.job()).toEqual(REVERTED);
      expect(store.reverting.rehearsal()).toBe(false);

      store.deploy(REHEARSAL);
      expect(store.reverting.job()).toBeNull();
      http.expectOne(`/api/applications/${SOURCE}/deploy/`).flush({ activity: DEPLOY_ID }, { status: 202, statusText: 'Accepted' });
    });
  });
});
