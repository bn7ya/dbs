import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { ApplicationRef, type DebugElement } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MatButtonHarness } from '@angular/material/button/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatSelectHarness } from '@angular/material/select/testing';
import { By } from '@angular/platform-browser';
import { provideRouter, type Routes } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { of } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Identity } from '@core/auth/data/auth.types';
import { MASTER, OPERATOR } from '@core/auth/testing/identity.fixtures';
import { errorInterceptor } from '@core/http/error.interceptor';
import { JobWatcher } from '@core/jobs/job-watcher';
import type { Job } from '@core/jobs/job.types';
import { ConfirmedRun } from '../../components/confirmed-run/confirmed-run';
import { MoveApplication } from '../../components/move-application/move-application';
import type { DeployApplication } from '../../data/redeploy.types';
import {
  APPLICATIONS,
  BACKUPS,
  COMPOSE_APPLICATION,
  DEPLOYED,
  DEPLOYING,
  DEPLOY_ID,
  DEPLOY_STOPPED,
  ENV_VERSIONS,
  HOST_APPLICATION,
  MOVED_FROM_CHOSEN,
  MOVE_ID,
  MOVE_STOPPED,
  MOVING,
  REHEARSED_WITHOUT_SOURCE,
  REVERTED,
  REVERT_ID,
  SOURCE,
  TARGET,
  pageOf,
} from '../../testing/redeploy.fixtures';
import { RedeployPage } from './redeploy';

const ROUTES: Routes = [
  {
    path: 'applications/:applicationId',
    children: [{ path: 'deploy', loadChildren: () => import('../../redeploy.routes').then((m) => m.routes) }],
  },
];

const DEPLOY = 'app-deploy-here';
const MOVE = 'app-move-application';

describe('RedeployPage', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;
  let watched: Map<number, Job>;

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const show = async (application: DeployApplication = COMPOSE_APPLICATION, identity: Identity = MASTER): Promise<void> => {
    harness = await RouterTestingHarness.create();
    const navigating = harness.navigateByUrl(`/applications/${SOURCE}/deploy`, RedeployPage);
    (await vi.waitFor(() => http.expectOne('/api/auth/me/'))).flush(identity);
    await navigating;
    TestBed.tick();
    http.expectOne(`/api/applications/${SOURCE}/`).flush(application);
    http.expectOne((request) => request.url === '/api/applications/').flush(pageOf(APPLICATIONS));
    const backups = http.expectOne((request) => request.url === '/api/backups/');
    expect(backups.request.params.get('application')).toBe(SOURCE);
    backups.flush(pageOf(BACKUPS));
    const versions = http.expectOne((request) => request.url === '/api/envfiles/');
    expect(versions.request.params.get('application')).toBe(SOURCE);
    versions.flush(pageOf(ENV_VERSIONS));
    await settle();
    harness.detectChanges();
  };

  const render = (): void => harness.detectChanges();
  const debugOf = (selector: string): DebugElement => {
    const found = harness.routeDebugElement?.query(By.css(selector));
    if (!found) {
      throw new Error(`${selector} is not on screen.`);
    }
    return found;
  };
  const section = (selector: string): HTMLElement => {
    render();
    return debugOf(selector).nativeElement as HTMLElement;
  };
  const runs = (selector: string): ConfirmedRun[] =>
    debugOf(selector)
      .queryAll(By.directive(ConfirmedRun))
      .map((found) => found.componentInstance as ConfirmedRun);
  const moveSection = (): MoveApplication => debugOf(MOVE).componentInstance as MoveApplication;
  const buttonIn = (root: HTMLElement, text: string): HTMLButtonElement | undefined =>
    Array.from(root.querySelectorAll('button')).find((button) => button.textContent?.trim() === text);
  const stepsOf = (root: Element | null): (string | undefined)[][] =>
    Array.from(root?.querySelectorAll('app-steps-list li') ?? [], (step) => [
      step.querySelector('span')?.textContent?.trim(),
      step.querySelector('app-status-tag')?.textContent?.trim(),
    ]);
  const started = (url: string, id: number): void => {
    http.expectOne(url).flush({ activity: id }, { status: 202, statusText: 'Accepted' });
    render();
  };

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    watched = new Map();
    TestBed.configureTestingModule({
      providers: [
        { provide: JobWatcher, useValue: { watch: (id: number) => of(watched.get(id)) } },
        { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter(ROUTES),
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  describe('deploy here', () => {
    it('lists the saved steps in order, with what each one does and how long it may take', async () => {
      await show();

      const deploy = section(DEPLOY);
      expect(deploy.querySelector('h2')?.textContent?.trim()).toBe('Deploy here');
      const rows = Array.from(deploy.querySelectorAll('.deploy__step'), (row) =>
        Array.from(row.querySelectorAll('.deploy__stack > span'), (line) => line.textContent?.trim()),
      );
      expect(rows).toEqual([
        ['Pull the code (git pull)', 'From ⁨origin⁩, branch ⁨main⁩', 'Time limit: 5 min'],
        [
          'Build images (compose build)',
          'Services: ⁨web⁩ and ⁨worker⁩',
          'Pulls newer base images',
          'Time limit: 30 min',
        ],
        ['Start services (compose up)', 'Every service', 'Time limit: 10 min'],
        ['Run the migrations', 'Time limit: 10 min'],
      ]);
      expect(buttonIn(deploy, 'Edit steps')).toBeDefined();
      expect(deploy.textContent).toContain('git fetch --dry-run, compose config, migrate --plan, collectstatic --dry-run');

      const loader = TestbedHarnessEnvironment.loader(harness.fixture);
      expect(await (await loader.getHarness(MatButtonHarness.with({ text: 'Deploy' }))).getAppearance()).toBe('filled');
      expect(await (await loader.getHarness(MatButtonHarness.with({ text: 'Move for real' }))).getAppearance()).toBe(
        'outlined',
      );
    });

    it('rehearses without the password and follows the job, each deploy step by its label', async () => {
      watched.set(DEPLOY_ID, { ...DEPLOYING, detail: { ...DEPLOYING.detail, rehearsal: true } });
      await show();

      buttonIn(section(DEPLOY), 'Rehearse')?.click();
      const post = http.expectOne(`/api/applications/${SOURCE}/deploy/`);
      expect(post.request.body).toEqual({ rehearsal: true, password: '', confirm_name: '' });
      post.flush({ activity: DEPLOY_ID }, { status: 202, statusText: 'Accepted' });

      const progress = section(DEPLOY).querySelector('app-job-progress');
      expect(progress?.querySelector('h3')?.textContent?.trim()).toBe('Rehearsal');
      expect(stepsOf(progress)).toEqual([
        ['Check the application', 'Done'],
        ['Take a safety backup', 'Done'],
        ['Record the .env file', 'Done'],
        ['Pull the code (git pull)', 'Running'],
        ['Build images (compose build)', 'Waiting'],
        ['Check again', 'Waiting'],
      ]);
      expect(progress?.querySelector('app-job-connection')?.textContent).toContain('Connection alive');
    });

    it('deploys for real only with the password and the application name typed out', async () => {
      await show();
      const [run] = runs(DEPLOY);
      expect(section(DEPLOY).textContent).toContain('Type ⁨Shop⁩ to deploy for real.');

      buttonIn(section(DEPLOY), 'Deploy')?.click();
      http.expectNone(`/api/applications/${SOURCE}/deploy/`);
      expect(run.passwordError()).toBe('Enter your password.');
      expect(run.nameError()).toBe("Type the application's name exactly as shown.");

      run.setPassword('secret');
      run.setTypedName(' Shop ');
      run.runForReal();
      const post = http.expectOne(`/api/applications/${SOURCE}/deploy/`);
      expect(post.request.body).toEqual({ rehearsal: false, password: 'secret', confirm_name: 'Shop' });
      post.flush({ error: { code: 'invalid_password', message: 'Server prose' } }, { status: 400, statusText: 'Bad Request' });
      render();

      expect(run.passwordError()).toBe('The password is not correct.');
      run.setPassword('right');
      render();
      expect(run.passwordError()).toBe('');
    });

    it('shows the code and the image before and after a deploy that finished', async () => {
      watched.set(DEPLOY_ID, DEPLOYED);
      await show();
      const [run] = runs(DEPLOY);
      run.setPassword('secret');
      run.setTypedName('Shop');
      run.runForReal();
      started(`/api/applications/${SOURCE}/deploy/`, DEPLOY_ID);

      const deploy = section(DEPLOY);
      expect(deploy.textContent).toContain('The deploy finished.');
      const revisions = Array.from(deploy.querySelectorAll('.deploy__revision'), (row) =>
        Array.from(row.querySelectorAll('dt, bdi'), (cell) => cell.textContent?.trim()),
      );
      expect(revisions).toEqual([
        ['Code commit', 'a1b2c3d4e5f6', 'f6e5d4c3b2a1'],
        ['Image', 'sha256:0123456789abcdef', 'sha256:fedcba9876543210'],
      ]);
      expect(deploy.querySelector('app-revert-panel')).toBeNull();
    });

    it('names the step a deploy stopped at and restores the safety backup, saying it puts the data back only', async () => {
      watched.set(DEPLOY_ID, DEPLOY_STOPPED).set(REVERT_ID, REVERTED);
      await show();
      const [run] = runs(DEPLOY);
      run.setPassword('secret');
      run.setTypedName('Shop');
      run.runForReal();
      started(`/api/applications/${SOURCE}/deploy/`, DEPLOY_ID);

      const deploy = section(DEPLOY);
      expect(deploy.textContent).toContain('The deploy stopped at: Build images (compose build).');
      expect(deploy.textContent).toContain('A command on the server failed.');
      const panel = deploy.querySelector('app-revert-panel');
      expect(panel?.querySelector('h3')?.textContent?.trim()).toBe('Restore the safety backup');
      expect(panel?.textContent).toContain('It puts the data back only: the code and the images stay as the deploy left them.');

      const restore = runs(DEPLOY)[1];
      restore.runForReal();
      http.expectNone(`/api/redeploy/${DEPLOY_ID}/revert/`);
      expect(restore.passwordError()).toBe('Enter your password.');

      restore.setPassword('secret');
      restore.setTypedName('Shop');
      restore.runForReal();
      const revert = http.expectOne(`/api/redeploy/${DEPLOY_ID}/revert/`);
      expect(revert.request.body).toEqual({ rehearsal: false, password: 'secret', confirm_name: 'Shop' });
      revert.flush({ activity: REVERT_ID }, { status: 202, statusText: 'Accepted' });

      const undone = section(DEPLOY).querySelector('app-revert-panel app-job-progress');
      expect(undone?.querySelector('h4')?.textContent?.trim()).toBe('Restoring');
      expect(stepsOf(undone)).toEqual([
        ['Check the application', 'Done'],
        ['Push the recorded .env file back', 'Done'],
        ['Restore the safety backup', 'Done'],
      ]);
      expect(undone?.textContent).toContain('The data is back as it was before the deploy.');
    });

    it('rehearses the restore without the password', async () => {
      watched.set(DEPLOY_ID, DEPLOY_STOPPED).set(REVERT_ID, { ...REVERTED, detail: { rehearsal: true, steps: [] } });
      await show();
      const [run] = runs(DEPLOY);
      run.setPassword('secret');
      run.setTypedName('Shop');
      run.runForReal();
      started(`/api/applications/${SOURCE}/deploy/`, DEPLOY_ID);

      buttonIn(section(DEPLOY), 'Rehearse the restore')?.click();
      const revert = http.expectOne(`/api/redeploy/${DEPLOY_ID}/revert/`);
      expect(revert.request.body).toEqual({ rehearsal: true, password: '', confirm_name: '' });
      revert.flush({ activity: REVERT_ID }, { status: 202, statusText: 'Accepted' });

      expect(section(DEPLOY).textContent).toContain('The restore rehearsal finished. Nothing was changed.');
    });

    it('says why a deploy was refused, and when a saved step no longer fits instead of asking to check fields', async () => {
      await show();
      buttonIn(section(DEPLOY), 'Rehearse')?.click();
      http
        .expectOne(`/api/applications/${SOURCE}/deploy/`)
        .flush({ error: { code: 'no_deploy_steps', message: 'Server prose' } }, { status: 409, statusText: 'Conflict' });
      expect(section(DEPLOY).querySelector('app-confirmed-run app-notice')?.textContent).toContain(
        'This application has no deploy steps yet. Choose them first.',
      );

      buttonIn(section(DEPLOY), 'Rehearse')?.click();
      http
        .expectOne(`/api/applications/${SOURCE}/deploy/`)
        .flush(
          { error: { code: 'invalid', message: 'Server prose', fields: { 'steps.1': ['compose_required'] } } },
          { status: 400, statusText: 'Bad Request' },
        );
      const deploy = section(DEPLOY);
      expect(deploy.textContent).toContain('A saved step no longer fits this application. Edit the steps, then deploy.');
      expect(deploy.textContent).not.toContain('Check the marked fields.');
    });

    it('marks a saved step that no longer fits the application', async () => {
      await show({ ...COMPOSE_APPLICATION, kind: 'container' });

      const warnings = Array.from(section(DEPLOY).querySelectorAll('.deploy__step app-notice'), (notice) =>
        notice.textContent?.trim(),
      );
      expect(warnings).toEqual([
        'This step runs only for an application in a Compose service.',
        'This step runs only for an application in a Compose service.',
      ]);
    });

    it('offers to choose the steps when there are none, and nothing to rehearse yet', async () => {
      await show(HOST_APPLICATION);

      const deploy = section(DEPLOY);
      expect(deploy.querySelector('app-empty-state')?.textContent).toContain('No deploy steps yet');
      expect(buttonIn(deploy, 'Rehearse')).toBeUndefined();

      buttonIn(deploy, 'Choose the steps')?.click();
      expect(section(DEPLOY).querySelector('app-deploy-steps-editor')).not.toBeNull();
      buttonIn(section(DEPLOY), 'Cancel')?.click();
      expect(section(DEPLOY).querySelector('app-deploy-steps-editor')).toBeNull();
    });
  });

  describe('move to another application', () => {
    it('offers every other application with its server, and the newest django-dbs backup and .env version first', async () => {
      await show();
      const loader = TestbedHarnessEnvironment.loader(harness.fixture);
      const [target, backup] = await loader.getAllHarnesses(MatSelectHarness);

      await target.open();
      const options = await target.getOptions();
      expect(await Promise.all(options.map((option) => option.getText()))).toEqual(['⁨Shop next⁩ on ⁨New web⁩']);
      await target.close();
      await backup.open();
      const backups = await Promise.all((await backup.getOptions()).map((option) => option.getText()));
      expect(backups[0]).toBe('None: stop if this application does not answer');
      expect(backups.some((name) => name.includes('media.tar.gz'))).toBe(false);

      const move = moveSection();
      expect(move.backup()).toBe('b-new');
      expect(move.envVersion()).toBe('env-new');
      expect(move.flush()).toBe(false);
      expect(section(MOVE).querySelector('h2')?.textContent?.trim()).toBe('Move to another application');
      expect(section(MOVE).textContent).toContain("The new application must already run the project's code");
    });

    it('rehearses without the password and shows each step and the connection as it goes', async () => {
      watched.set(MOVE_ID, MOVING);
      await show();
      moveSection().target.set(TARGET);

      buttonIn(section(MOVE), 'Rehearse')?.click();
      const post = http.expectOne('/api/redeploy/');
      expect(post.request.body).toEqual({
        source_application: SOURCE,
        target_application: TARGET,
        backup: 'b-new',
        env_version: 'env-new',
        flush: false,
        rehearsal: true,
        password: '',
        confirm_name: '',
      });
      post.flush({ activity: MOVE_ID }, { status: 202, statusText: 'Accepted' });

      const progress = section(MOVE).querySelector('app-job-progress');
      expect(stepsOf(progress)).toEqual([
        ['Check the new application', 'Done'],
        ['Back up this application now', 'Running'],
        ["Record the new application's .env file", 'Skipped'],
      ]);
      expect(progress?.querySelector('app-job-connection')?.textContent).toContain('Connection alive');
    });

    it('moves for real only with a target, the password and its name typed out', async () => {
      await show();
      const [run] = runs(MOVE);

      run.runForReal();
      http.expectNone('/api/redeploy/');
      expect(section(MOVE).textContent).toContain('Choose the application to move to.');

      moveSection().target.set(TARGET);
      render();
      run.setTypedName('shop next');
      run.runForReal();
      http.expectNone('/api/redeploy/');
      expect(run.passwordError()).toBe('Enter your password.');
      expect(run.nameError()).toBe("Type the application's name exactly as shown.");

      run.setPassword('secret');
      run.setTypedName(' Shop next ');
      moveSection().flush.set(true);
      moveSection().backup.set(null);
      run.runForReal();
      const post = http.expectOne('/api/redeploy/');
      expect(post.request.body).toMatchObject({
        backup: null,
        flush: true,
        rehearsal: false,
        password: 'secret',
        confirm_name: 'Shop next',
      });
      post.flush(
        { error: { code: 'passphrase_missing', message: 'Server prose' } },
        { status: 400, statusText: 'Bad Request' },
      );
      expect(section(MOVE).querySelector('app-notice[role="alert"]')?.textContent).toContain(
        'The backup passphrase of this application is not saved here.',
      );
    });

    it('names the step a move stopped at and reverts the new application only with its name and the password', async () => {
      watched.set(MOVE_ID, MOVE_STOPPED).set(REVERT_ID, REVERTED);
      await show();
      moveSection().target.set(TARGET);
      render();
      const [run] = runs(MOVE);
      run.setPassword('secret');
      run.setTypedName('Shop next');
      run.runForReal();
      started('/api/redeploy/', MOVE_ID);

      expect(section(MOVE).textContent).toContain('The move stopped at: Run the migrations.');
      expect(section(MOVE).querySelector('app-revert-panel h3')?.textContent?.trim()).toBe('Revert the new application');

      const revert = runs(MOVE)[1];
      expect(revert.expectedName()).toBe('Shop next');
      revert.runForReal();
      http.expectNone(`/api/redeploy/${MOVE_ID}/revert/`);
      expect(revert.nameError()).toBe("Type the application's name exactly as shown.");

      revert.setPassword('secret');
      revert.setTypedName('Shop next');
      revert.runForReal();
      const request = http.expectOne(`/api/redeploy/${MOVE_ID}/revert/`);
      expect(request.request.body).toEqual({ rehearsal: false, password: 'secret', confirm_name: 'Shop next' });
      request.flush({ activity: REVERT_ID }, { status: 202, statusText: 'Accepted' });

      expect(stepsOf(section(MOVE).querySelector('app-revert-panel app-job-progress'))).toEqual([
        ['Check the application', 'Done'],
        ['Push the recorded .env file back', 'Done'],
        ['Restore the safety backup', 'Done'],
      ]);
      expect(section(MOVE).textContent).toContain('The new application is back as it was before the move.');
    });

    it('says so when this application did not answer and the chosen backup was restored', async () => {
      watched.set(MOVE_ID, MOVED_FROM_CHOSEN);
      await show();
      moveSection().target.set(TARGET);
      render();
      const [run] = runs(MOVE);
      run.setPassword('secret');
      run.setTypedName('Shop next');
      run.runForReal();
      started('/api/redeploy/', MOVE_ID);

      expect(section(MOVE).textContent).toContain('This application did not answer, so the chosen backup was restored.');
      expect(section(MOVE).querySelector('app-revert-panel')).toBeNull();
    });

    it('says when a rehearsal found this application silent', async () => {
      watched.set(MOVE_ID, REHEARSED_WITHOUT_SOURCE);
      await show();
      moveSection().target.set(TARGET);
      buttonIn(section(MOVE), 'Rehearse')?.click();
      started('/api/redeploy/', MOVE_ID);

      expect(section(MOVE).textContent).toContain('A move now would restore the chosen backup instead of a fresh one.');
    });
  });

  it('leaves out what an operator may not do: editing the steps, and anything for real', async () => {
    await show(COMPOSE_APPLICATION, OPERATOR);

    const deploy = section(DEPLOY);
    expect(buttonIn(deploy, 'Edit steps')).toBeUndefined();
    expect(buttonIn(deploy, 'Rehearse')).toBeDefined();
    expect(buttonIn(deploy, 'Deploy')).toBeUndefined();
    expect(deploy.querySelector('app-password-input')).toBeNull();
    const move = section(MOVE);
    expect(buttonIn(move, 'Rehearse')).toBeDefined();
    expect(buttonIn(move, 'Move for real')).toBeUndefined();
    expect(move.querySelector('app-password-input')).toBeNull();
  });
});
