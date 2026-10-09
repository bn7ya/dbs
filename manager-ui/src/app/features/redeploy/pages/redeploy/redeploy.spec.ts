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
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { RedeployStore } from '../../state/redeploy.store';
import { BACKUPS, ENV_VERSIONS, RUNNING, SERVERS, SOURCE, pageOf } from '../../testing/redeploy.fixtures';
import { RedeployPage } from './redeploy';

const TARGET = SERVERS[1];

describe('RedeployPage', () => {
  let http: HttpTestingController;
  let fixture: ComponentFixture<RedeployPage>;
  let page: RedeployPage;

  const html = (): HTMLElement => {
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  };

  beforeEach(async () => {
    localStorage.setItem('locale', 'en');
    const params = convertToParamMap({ serverId: SOURCE });
    TestBed.configureTestingModule({
      providers: [
        RedeployStore,
        { provide: JobWatcher, useValue: { watch: () => of(RUNNING) } },
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
    const [target] = await loader.getAllHarnesses(MatSelectHarness);
    await target.open();
    const options = await target.getOptions();
    expect(await Promise.all(options.map((option) => option.getText()))).toEqual(['New web']);

    expect(page.backup()).toBe('b-new');
    expect(page.envVersion()).toBe('env-new');
    expect(page.archiveOptions().map((archive) => archive.id)).toEqual(['a-media']);
    expect(page.migrate()).toBe(true);
    expect(page.flush()).toBe(false);
    expect(html().textContent).toContain("The other server must already have the project's code");
  });

  it('rehearses without the password and shows each step as it goes', () => {
    page.target.set(TARGET.id);
    page.rehearse();

    const post = http.expectOne('/api/redeploy/');
    expect(post.request.body).toEqual({
      source_server: SOURCE,
      target_server: TARGET.id,
      backup: 'b-new',
      env_version: 'env-new',
      archives: [],
      migrate: true,
      flush: false,
      rehearsal: true,
      password: '',
      confirm_name: '',
    });
    post.flush({ activity: 9 }, { status: 202, statusText: 'Accepted' });

    const steps = Array.from(html().querySelectorAll('.redeploy__step'), (step) => [
      step.querySelector('span')?.textContent?.trim(),
      step.querySelector('app-status-tag')?.textContent?.trim(),
    ]);
    expect(steps).toEqual([
      ['Check the other server', 'Done'],
      ['Push the .env file', 'Running'],
      ['Run the migrations', 'Waiting'],
    ]);
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
    expect(page.nameError()).toBe("Type the other server's name exactly as shown.");

    page.setPassword('secret');
    page.setConfirmName(` ${TARGET.name} `);
    page.archives.set(['a-media']);
    page.flush.set(true);
    page.moveForReal();
    const post = http.expectOne('/api/redeploy/');
    expect(post.request.body).toMatchObject({
      archives: ['a-media'],
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
});
