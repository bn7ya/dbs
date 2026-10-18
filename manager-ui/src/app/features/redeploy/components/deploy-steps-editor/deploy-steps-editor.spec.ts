import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestKey } from '@angular/cdk/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { ApplicationRef } from '@angular/core';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { MatCheckboxHarness } from '@angular/material/checkbox/testing';
import { MatChipGridHarness } from '@angular/material/chips/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatMenuHarness } from '@angular/material/menu/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import { Dialogs } from '@shared/dialogs/dialogs';
import { PasswordPrompt } from '@shared/password-prompt/password-prompt';
import type { PasswordPromptData } from '@shared/password-prompt/password-prompt.types';
import { Toaster } from '@shared/toaster/toaster';
import type { DeployApplication } from '../../data/redeploy.types';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { DeployStore } from '../../state/deploy.store';
import { COMPOSE_APPLICATION, HOST_APPLICATION, MIGRATE, PULL, SOURCE } from '../../testing/redeploy.fixtures';
import { DeployStepsEditor } from './deploy-steps-editor';

describe('DeployStepsEditor', () => {
  let fixture: ComponentFixture<DeployStepsEditor>;
  let editor: DeployStepsEditor;
  let http: HttpTestingController;
  let closed: number;

  const settle = (): Promise<void> => TestBed.inject(ApplicationRef).whenStable();

  const create = async (application: DeployApplication = COMPOSE_APPLICATION): Promise<void> => {
    const store = TestBed.inject(DeployStore);
    store.open(SOURCE);
    TestBed.tick();
    http.expectOne(`/api/applications/${SOURCE}/`).flush(application);
    await settle();
    fixture = TestBed.createComponent(DeployStepsEditor);
    fixture.componentRef.setInput('application', application);
    editor = fixture.componentInstance;
    closed = 0;
    editor.closed.subscribe(() => (closed += 1));
    await render();
  };

  const render = async (): Promise<void> => {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  };

  const element = (): HTMLElement => fixture.nativeElement as HTMLElement;
  const rows = (): HTMLElement[] => Array.from(element().querySelectorAll<HTMLElement>('.editor__step'));
  const headers = (): (string | undefined)[] =>
    rows().map((row) => row.querySelector('.editor__step-header .text-label')?.textContent?.trim());
  const errors = (): (string | undefined)[] =>
    Array.from(element().querySelectorAll('mat-error'), (error) => error.textContent?.trim());
  const notices = (): (string | undefined)[] =>
    Array.from(element().querySelectorAll('app-notice'), (notice) => notice.textContent?.trim());
  const buttonNamed = (name: string): HTMLButtonElement | undefined =>
    Array.from(element().querySelectorAll('button')).find(
      (button) => button.getAttribute('aria-label') === name || button.textContent?.trim() === name,
    );

  const stubPrompt = (): { open: MockInstance<Dialogs['open']>; close: (answer: boolean) => void } => {
    let close: (answer: boolean) => void = () => undefined;
    const answered = new Promise<boolean>((resolve) => (close = resolve));
    const open = vi
      .spyOn(TestBed.inject(Dialogs), 'open')
      .mockReturnValue({ closed: of(true), whenClosed: () => answered });
    return { open, close };
  };

  const promptOf = (open: MockInstance<Dialogs['open']>): PasswordPromptData => {
    const [component, options] = open.mock.calls[0];
    expect(component).toBe(PasswordPrompt);
    return options.data as PasswordPromptData;
  };

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [
        DeployStore,
        Dialogs,
        { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    TestBed.inject(LocaleStore).register({ en, ar });
    vi.spyOn(TestBed.inject(Toaster), 'add').mockReturnValue(undefined);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('shows each saved step with the fields its kind takes, filled in', async () => {
    await create();

    expect(headers()).toEqual([
      'Step 1: Pull the code (git pull)',
      'Step 2: Build images (compose build)',
      'Step 3: Start services (compose up)',
      'Step 4: Run the migrations',
    ]);
    const values = rows().map((row) =>
      Array.from(row.querySelectorAll<HTMLInputElement>('input[matinput]'), (input) => input.value),
    );
    expect(values).toEqual([['origin', 'main', '5'], ['30'], ['10'], ['10']]);
    const loader = TestbedHarnessEnvironment.loader(fixture);
    const grids = await loader.getAllHarnesses(MatChipGridHarness);
    expect(grids).toHaveLength(2);
    expect(await Promise.all((await grids[0].getRows()).map((chip) => chip.getText()))).toEqual(['web', 'worker']);
    expect(await (await loader.getHarness(MatCheckboxHarness)).isChecked()).toBe(true);
  });

  it('offers to add only the kinds that fit the application', async () => {
    await create();

    buttonNamed('Add a step')?.click();
    const menu = await TestbedHarnessEnvironment.documentRootLoader(fixture).getHarness(MatMenuHarness);
    expect(await Promise.all((await menu.getItems()).map((item) => item.getText()))).toEqual([
      'Pull the code (git pull)',
      'Pull images (compose pull)',
      'Build images (compose build)',
      'Start services (compose up)',
      'Restart the container or service',
      'Restart a user service (systemctl --user)',
      'Run the migrations',
      'Collect static files',
    ]);

    await menu.clickItem({ text: 'Collect static files' });
    await render();
    expect(headers().at(-1)).toBe('Step 5: Collect static files');
  });

  it('says git pull and pip install need the folder of an application without one', async () => {
    await create(HOST_APPLICATION);

    expect(element().textContent).toContain('No steps. Saving leaves nothing to deploy.');
    expect(element().textContent).toContain("Git pull and pip install need the application's folder.");
    buttonNamed('Add a step')?.click();
    const menu = await TestbedHarnessEnvironment.documentRootLoader(fixture).getHarness(MatMenuHarness);
    expect(await Promise.all((await menu.getItems()).map((item) => item.getText()))).toEqual([
      'Restart a user service (systemctl --user)',
      'Run the migrations',
      'Collect static files',
    ]);
  });

  it('moves and removes steps, each keeping its own fields', async () => {
    await create();

    buttonNamed('Move step 1 down')?.click();
    await render();
    expect(headers().slice(0, 2)).toEqual(['Step 1: Build images (compose build)', 'Step 2: Pull the code (git pull)']);
    expect(Array.from(rows()[1].querySelectorAll<HTMLInputElement>('input[matinput]'), (input) => input.value)).toEqual([
      'origin',
      'main',
      '5',
    ]);

    buttonNamed('Move step 4 up')?.click();
    buttonNamed('Remove step 1')?.click();
    await render();
    expect(headers()).toEqual([
      'Step 1: Pull the code (git pull)',
      'Step 2: Run the migrations',
      'Step 3: Start services (compose up)',
    ]);
    // Disabled but still focusable, so focus stays on a step moved to an end of the list.
    expect(buttonNamed('Move step 1 up')?.getAttribute('aria-disabled')).toBe('true');
    expect(buttonNamed('Move step 3 down')?.getAttribute('aria-disabled')).toBe('true');
    expect(buttonNamed('Move step 2 up')?.getAttribute('aria-disabled')).not.toBe('true');

    buttonNamed('Move step 1 up')?.click();
    await render();
    expect(headers()[0]).toBe('Step 1: Pull the code (git pull)');
  });

  it('stops at twelve steps', async () => {
    await create();

    for (let added = 0; added < 10; added += 1) {
      editor.add('migrate');
    }
    await render();

    expect(rows()).toHaveLength(12);
    expect(buttonNamed('Add a step')?.disabled).toBe(true);
    expect(element().textContent).toContain('A deploy runs at most twelve steps.');
  });

  it('adds Compose services as chips, each once, and removes them', async () => {
    await create();
    const grid = (await TestbedHarnessEnvironment.loader(fixture).getAllHarnesses(MatChipGridHarness))[1];
    const input = await grid.getInput();

    await input?.setValue('web');
    await input?.sendSeparatorKey(TestKey.ENTER);
    await input?.setValue(' web ');
    await input?.sendSeparatorKey(TestKey.ENTER);
    expect(editor.drafts()[2].services).toEqual(['web']);

    await (await grid.getRows())[0].remove();
    expect(editor.drafts()[2].services).toEqual([]);
  });

  it('shows each field problem once saving is tried, and asks for no password while one is left', async () => {
    await create();
    const { open } = stubPrompt();
    editor.update(0, { branch: '' });
    editor.update(3, { timeout: 0 });
    await render();
    expect(errors()).toEqual([]);

    await editor.save();
    await render();

    expect(open).not.toHaveBeenCalled();
    expect(errors()).toEqual(['Name the branch together with its remote.', 'Allow 1 to 120 minutes.']);
  });

  it('refuses to save a step that no longer fits the application', async () => {
    await create({ ...COMPOSE_APPLICATION, kind: 'container' });
    const { open } = stubPrompt();

    expect(notices()).toEqual([
      'This step runs only for an application in a Compose service.',
      'This step runs only for an application in a Compose service.',
    ]);
    await editor.save();
    expect(open).not.toHaveBeenCalled();

    buttonNamed('Remove step 3')?.click();
    buttonNamed('Remove step 2')?.click();
    await render();
    void editor.save();
    await vi.waitFor(() => expect(open).toHaveBeenCalledOnce());
  });

  it('saves the steps behind the password, then closes', async () => {
    await create();
    const { open, close } = stubPrompt();
    editor.remove(1);
    editor.remove(1);

    const saving = editor.save();
    await vi.waitFor(() => expect(open).toHaveBeenCalledOnce());
    const prompt = promptOf(open);
    expect(prompt).toMatchObject({ titleKey: 'redeploy.editor.prompt.title', submitKey: 'redeploy.editor.save' });

    const submitting = prompt.submit('hunter2');
    const request = http.expectOne(`/api/applications/${SOURCE}/deploy-steps/`);
    expect(request.request.body).toEqual({ steps: [PULL, MIGRATE], account_password: 'hunter2' });
    request.flush({ ...COMPOSE_APPLICATION, deploy_steps: [PULL, MIGRATE] });
    await expect(submitting).resolves.toBe(true);
    close(true);
    await saving;

    expect(closed).toBe(1);
  });

  it('puts a refusal of the steps on their rows, and closes the prompt with nothing to retry', async () => {
    await create();
    const { open, close } = stubPrompt();

    const saving = editor.save();
    await vi.waitFor(() => expect(open).toHaveBeenCalledOnce());
    const submitting = promptOf(open).submit('hunter2');
    http
      .expectOne(`/api/applications/${SOURCE}/deploy-steps/`)
      .flush(
        {
          error: {
            code: 'invalid',
            message: 'Server prose',
            fields: { 'steps.1': ['compose_required'], steps: ['too_many_steps'] },
          },
        },
        { status: 400, statusText: 'Bad Request' },
      );
    await expect(submitting).resolves.toBe(true);
    close(true);
    await saving;
    await render();

    expect(closed).toBe(0);
    expect(notices()).toEqual([
      'A deploy runs at most twelve steps.',
      'This step runs only for an application in a Compose service.',
    ]);

    editor.update(0, { branch: 'develop' });
    await render();
    expect(notices()).toEqual([]);
  });

  it('keeps the prompt open on a wrong password', async () => {
    await create();
    const { open, close } = stubPrompt();

    const saving = editor.save();
    await vi.waitFor(() => expect(open).toHaveBeenCalledOnce());
    const prompt = promptOf(open);
    const submitting = prompt.submit('wrong');
    http
      .expectOne(`/api/applications/${SOURCE}/deploy-steps/`)
      .flush({ error: { code: 'invalid_password', message: 'Server prose' } }, { status: 400, statusText: 'Bad Request' });

    await expect(submitting).resolves.toBe(false);
    expect(prompt.error()?.code).toBe('invalid_password');
    close(false);
    await saving;
    expect(closed).toBe(0);
  });

  it('closes on cancel, saving nothing', async () => {
    await create();

    buttonNamed('Cancel')?.click();

    expect(closed).toBe(1);
  });
});
