import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { ApplicationRef } from '@angular/core';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatSelectHarness } from '@angular/material/select/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import { JobWatcher } from '@core/jobs/job-watcher';
import type { Job } from '@core/jobs/job.types';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { RedeployStore } from '../../state/redeploy.store';
import {
  BACKUPS,
  ENV_VERSIONS,
  MOVED_FROM_CHOSEN,
  MOVE_ID,
  REHEARSED_WITHOUT_SOURCE,
  REVERTED,
  REVERT_ID,
  RUNNING,
  SERVERS,
  SOURCE,
  STOPPED,
  pageOf,
} from '../../testing/redeploy.fixtures';
import { RedeployPage } from './redeploy';

const TARGET = SERVERS[1];

describe('RedeployPage', () => {
  let http: HttpTestingController;
  let fixture: ComponentFixture<RedeployPage>;
  let page: RedeployPage;
  let watched: Map<number, Job>;

  const html = (): HTMLElement => {
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  };
  const steps = (): (string | undefined)[][] =>
    Array.from(html().querySelectorAll('app-move-steps li'), (step) => [
      step.querySelector('span')?.textContent?.trim(),
      step.querySelector('app-status-tag')?.textContent?.trim(),
    ]);
  const started = (id: number): void => {
    http.expectOne(id === MOVE_ID ? '/api/redeploy/' : `/api/redeploy/${MOVE_ID}/revert/`).flush(
      { activity: id },
      { status: 202, statusText: 'Accepted' },
    );
  };

  beforeEach(async () => {
    localStorage.setItem('locale', 'en');
    watched = new Map([[MOVE_ID, RUNNING]]);
    const params = convertToParamMap({ serverId: SOURCE });
    TestBed.configureTestingModule({
      providers: [
        RedeployStore,
        { provide: JobWatcher, useValue: { watch: (id: number) => of(watched.get(id)) } },
        { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: ActivatedRoute, useValue: { pathFromRoot: [{ snapshot: { paramMap: params }, paramMap: of(params) }] } },
      ],
    });
    TestBed.inject(LocaleStore).register({ en, ar });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(RedeployPage);
    page = fixture.componentInstance;
    fixture.detectChanges();
    (
      await vi.waitFor(() => {
        TestBed.tick();
        return http.expectOne((request) => request.url === '/api/servers/');
      })
    ).flush(pageOf(SERVERS));
    const backups = http.expectOne((request) => request.url === '/api/backups/');
    expect(backups.request.params.get('server')).toBe(SOURCE);
    backups.flush(pageOf(BACKUPS));
    http.expectOne((request) => request.url === '/api/envfiles/').flush(pageOf(ENV_VERSIONS));
    await TestBed.inject(ApplicationRef).whenStable();
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it('offers every other server, and the newest django-dbs backup and .env version first', async () => {
    html();
    const loader = TestbedHarnessEnvironment.loader(fixture);
    const [target, backup] = await loader.getAllHarnesses(MatSelectHarness);
    await target.open();
    const options = await target.getOptions();
    expect(await Promise.all(options.map((option) => option.getText()))).toEqual(['New web']);
    await target.close();
    await backup.open();
    const backups = await Promise.all((await backup.getOptions()).map((option) => option.getText()));
    expect(backups[0]).toBe('None: stop if this server does not answer');
    expect(backups.some((name) => name.includes('media.tar.gz'))).toBe(false);

    expect(page.backup()).toBe('b-new');
    expect(page.envVersion()).toBe('env-new');
    expect(page.flush()).toBe(false);
    expect(html().textContent).toContain("The new server must already run the project's code");
    expect(html().textContent).toContain('a fresh backup of it is taken now');
  });

  it('rehearses without the password and shows each step and the connection as it goes', () => {
    page.target.set(TARGET.id);
    page.rehearse();

    const post = http.expectOne('/api/redeploy/');
    expect(post.request.body).toEqual({
      source_server: SOURCE,
      target_server: TARGET.id,
      backup: 'b-new',
      env_version: 'env-new',
      flush: false,
      rehearsal: true,
      password: '',
      confirm_name: '',
    });
    post.flush({ activity: MOVE_ID }, { status: 202, statusText: 'Accepted' });

    expect(steps()).toEqual([
      ['Check the new server', 'Done'],
      ['Back up this server now', 'Running'],
      ["Record the new server's .env file", 'Waiting'],
    ]);
    expect(html().querySelector('app-job-connection')?.textContent).toContain('Connection alive');
  });

  it('moves for real only with the password and the target name typed out', () => {
    page.moveForReal();
    http.expectNone('/api/redeploy/');
    expect(html().textContent).toContain('Choose the server to move to.');

    page.target.set(TARGET.id);
    page.setConfirmName('new web');
    page.moveForReal();
    http.expectNone('/api/redeploy/');
    expect(page.passwordError()).toBe('Enter your password.');
    expect(page.nameError()).toBe("Type the new server's name exactly as shown.");

    page.setPassword('secret');
    page.setConfirmName(` ${TARGET.name} `);
    page.flush.set(true);
    page.backup.set(null);
    page.moveForReal();
    const post = http.expectOne('/api/redeploy/');
    expect(post.request.body).toMatchObject({
      backup: null,
      flush: true,
      rehearsal: false,
      password: 'secret',
      confirm_name: TARGET.name,
    });
    post.flush(
      { error: { code: 'passphrase_missing', message: 'Server prose' } },
      { status: 400, statusText: 'Bad Request' },
    );
    expect(html().querySelector('app-notice[role="alert"]')?.textContent).toContain(
      'The backup passphrase of this server is not saved here.',
    );
  });

  it('names the step a move stopped at and reverts the new server only with its name and the password', () => {
    watched.set(MOVE_ID, STOPPED).set(REVERT_ID, REVERTED);
    page.target.set(TARGET.id);
    page.setPassword('secret');
    page.setConfirmName(TARGET.name);
    page.moveForReal();
    started(MOVE_ID);

    expect(html().textContent).toContain('The move stopped at: Run the migrations.');
    expect(html().textContent).toContain('A command on the server failed.');
    expect(html().textContent).toContain('Revert the new server');

    page.revertForReal();
    http.expectNone(`/api/redeploy/${MOVE_ID}/revert/`);
    expect(page.revertPasswordError()).toBe('Enter your password.');
    expect(page.revertNameError()).toBe("Type the new server's name exactly as shown.");

    page.setRevertPassword('secret');
    page.setRevertName(TARGET.name);
    page.revertForReal();
    const revert = http.expectOne(`/api/redeploy/${MOVE_ID}/revert/`);
    expect(revert.request.body).toEqual({ rehearsal: false, password: 'secret', confirm_name: TARGET.name });
    revert.flush({ activity: REVERT_ID }, { status: 202, statusText: 'Accepted' });

    expect(steps().slice(-3)).toEqual([
      ['Check the new server', 'Done'],
      ['Push the recorded .env file back', 'Done'],
      ['Restore the data from before the move', 'Done'],
    ]);
    expect(html().textContent).toContain('The new server is back as it was before the move.');
  });

  it('rehearses the revert without the password', () => {
    watched.set(MOVE_ID, STOPPED).set(REVERT_ID, { ...REVERTED, detail: { steps: [] } });
    page.target.set(TARGET.id);
    page.setPassword('secret');
    page.setConfirmName(TARGET.name);
    page.moveForReal();
    started(MOVE_ID);

    page.rehearseRevert();
    const revert = http.expectOne(`/api/redeploy/${MOVE_ID}/revert/`);
    expect(revert.request.body).toEqual({ rehearsal: true, password: '', confirm_name: '' });
    revert.flush({ activity: REVERT_ID }, { status: 202, statusText: 'Accepted' });

    expect(html().textContent).toContain('The revert rehearsal finished. Nothing was changed.');
  });

  it('says so when this server did not answer and the chosen backup was restored', () => {
    watched.set(MOVE_ID, MOVED_FROM_CHOSEN);
    page.target.set(TARGET.id);
    page.setPassword('secret');
    page.setConfirmName(TARGET.name);
    page.moveForReal();
    started(MOVE_ID);

    expect(html().textContent).toContain('This server did not answer, so the chosen backup was restored.');
    expect(html().textContent).not.toContain('Revert the new server');
  });

  it('says when a rehearsal found this server silent', () => {
    watched.set(MOVE_ID, REHEARSED_WITHOUT_SOURCE);
    page.target.set(TARGET.id);
    page.rehearse();
    started(MOVE_ID);

    expect(html().textContent).toContain('A move now would restore the chosen backup instead of a fresh one.');
  });
});
