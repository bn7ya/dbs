import type { Locator, Page } from '@playwright/test';
import { Api } from './support/api';
import { ADMIN, ALLOWED_FOLDERS, FINGERPRINT, SSH } from './support/config';
import { baseUrlOf, expect, test } from './support/fixtures';
import type { Journey } from './support/fixtures.types';

test.describe.configure({ mode: 'serial' });

const stepIs = async (scope: Page | Locator, name: string): Promise<void> => {
  await expect(scope.getByRole('button', { name: new RegExp(`^${name}`), expanded: true })).toBeVisible();
};

const valueOf = (scope: Page | Locator, term: string): Locator =>
  scope.getByRole('term').filter({ hasText: term }).first().locator('xpath=following-sibling::*[1]');

export const fillAddress = async (form: Locator, { t }: Journey, name: string): Promise<void> => {
  await form.getByRole('textbox', { name: t('name'), exact: true }).fill(name);
  await form.getByRole('textbox', { name: t('host'), exact: true }).fill(SSH.host);
  await form.getByRole('spinbutton', { name: t('port') }).fill(String(SSH.port));
  await form.getByRole('textbox', { name: t('username') }).fill(SSH.username);
};

test.describe('adding a server and its application', () => {
  let name = '';
  let applicationName = '';
  let serverUrl = '';
  let applicationUrl = '';

  test.beforeAll(({}, testInfo) => {
    const stamp = `${testInfo.project.name} ${Date.now().toString(36)}`;
    name = `e2e wizard ${stamp}`;
    applicationName = `e2e wizard app ${stamp}`;
  });

  test.afterAll(async ({}, testInfo) => {
    // Only finds something when a step failed before the journey's own removal.
    const api = await Api.signIn(baseUrlOf(testInfo));
    await api.deleteServersNamed(name);
  });

  test('the address step reports what is missing or out of range', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto('/servers');
    await page.getByRole('main').getByRole('link', { name: t('addServer'), exact: true }).first().click();

    await expect(page).toHaveURL(/\/servers\/new$/);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(t('serverWizardTitle'));
    const form = page.getByRole('main');
    const next = form.getByRole('button', { name: t('next'), exact: true });
    await stepIs(form, t('stepAddress'));

    await next.click();
    await expect(form.getByText(t('fillIn'))).toHaveCount(3);
    await expect(form.getByRole('textbox', { name: t('name'), exact: true })).toHaveAccessibleDescription(
      new RegExp(t('fillIn')),
    );

    await form.getByRole('spinbutton', { name: t('port') }).fill('65536');
    await next.click();
    await expect(form.getByRole('spinbutton', { name: t('port') })).toHaveAttribute('aria-invalid', 'true');
    await expect(form.getByText(t('portRange'))).toBeVisible();
    await stepIs(form, t('stepAddress'));
    await journey.shot(page, 'add-server-validation');
  });

  test('a server takes its address, a confirmed host key, the SSH password and a check', async ({
    page,
    journey,
  }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto('/servers/new');
    const form = page.getByRole('main');
    const next = form.getByRole('button', { name: t('next'), exact: true });

    await fillAddress(form, journey, name);
    await next.click();

    await stepIs(form, t('stepHostKey'));
    await expect(form.getByRole('definition').filter({ hasText: /^SHA256:/ })).toHaveText(FINGERPRINT);
    await journey.shot(page, 'add-server-host-key');
    await next.click();
    await expect(form.getByText(t('compareFirst'))).toBeVisible();
    const match = form.getByRole('checkbox', { name: t('fingerprintsMatch') });
    await match.click();
    await expect(match).toBeChecked();
    await next.click();

    await stepIs(form, t('stepSignIn'));
    const passwordMethod = form.getByRole('radio', { name: t('password'), exact: true });
    await passwordMethod.click();
    await expect(passwordMethod).toBeChecked();
    await form.getByLabel(t('serverPassword'), { exact: true }).fill(SSH.password);
    await journey.shot(page, 'add-server-sign-in');
    await form.getByRole('button', { name: t('addServerSubmit'), exact: true }).click();

    await stepIs(form, t('stepCheck'));
    await expect(form.getByRole('status').filter({ hasText: t('canSignIn') })).toBeVisible({ timeout: 120_000 });
    await expect(valueOf(form, t('system'))).not.toBeEmpty();
    await journey.shot(page, 'add-server-check');
    await next.click();

    await stepIs(form, t('stepApplications'));
    await expect(form.getByText(t('serverReady'))).toBeVisible();
    await form.getByRole('button', { name: t('stepAddress') }).click();
    await stepIs(form, t('stepApplications'));
    const add = form.getByRole('link', { name: t('addApplication') });
    serverUrl = (await add.getAttribute('href'))!.replace(/\/applications\/new$/, '');
    expect(serverUrl).toMatch(/^\/servers\/[0-9a-f-]{36}$/);
    await add.click();
    await expect(page).toHaveURL(new RegExp(`${serverUrl}/applications/new$`));
  });

  test('an application is found from its folder, reviewed, checked, and backs up', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(`${serverUrl}/applications/new`);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(t('applicationWizardTitle'));
    const form = page.getByRole('main');
    const next = form.getByRole('button', { name: t('next'), exact: true });

    await stepIs(form, t('stepProfile'));
    await form.getByRole('radio', { name: t('runsInHost') }).check();
    await next.click();

    await stepIs(form, t('stepFolder'));
    await form.getByRole('textbox', { name: t('folderOnServer') }).fill(SSH.projectDir);
    await next.click();

    await stepIs(form, t('stepDiscovery'));
    const found = form.getByRole('radio', { name: `${t('onTheServer')} ${SSH.projectDir}` });
    await expect(found).toBeChecked({ timeout: 120_000 });
    await expect(valueOf(form, t('pythonWithDbs'))).toHaveText(SSH.python);
    await journey.shot(page, 'add-application-discovery');
    await next.click();

    await stepIs(form, t('stepReview'));
    await expect(form.getByRole('status').filter({ hasText: t('filledIn') })).toBeVisible();
    await form.getByRole('textbox', { name: t('name'), exact: true }).fill(applicationName);
    await form.getByRole('button', { name: t('showMoreSettings') }).click();
    await expect(form.getByRole('textbox', { name: t('projectFolder') })).toHaveValue(SSH.projectDir);
    await expect(form.getByRole('combobox', { name: t('pythonCommand') })).toHaveValue(SSH.python);
    await expect(form.getByRole('textbox', { name: t('backupFolder') })).toHaveValue(SSH.remoteBackupDir);
    await expect(form.getByRole('combobox', { name: t('envFile') })).toHaveValue(SSH.envPath);
    const folders = form.getByRole('textbox', { name: t('allowedFolders') });
    for (const folder of ALLOWED_FOLDERS) {
      await folders.fill(folder);
      await folders.press('Enter');
      await expect(form.getByRole('row', { name: new RegExp(`^${folder} `) })).toBeVisible();
    }
    await journey.shot(page, 'add-application-review');
    await form.getByRole('button', { name: t('addApplicationSubmit'), exact: true }).click();
    await journey.confirmPassword(page, 'continue');

    await stepIs(form, t('stepCheck'));
    await expect(form.getByText(t('versionsWork'))).toBeVisible({ timeout: 120_000 });
    await journey.shot(page, 'add-application-check');
    await next.click();

    await stepIs(form, t('stepPassphrase'));
    await form.getByRole('button', { name: t('readPassphrase') }).click();
    await expect(form.getByText(t('passphraseSaved'))).toBeVisible({ timeout: 60_000 });
    await next.click();

    await stepIs(form, t('stepTestBackup'));
    await form.getByRole('button', { name: t('takeTestBackup') }).click();
    await expect(form.getByText(t('testBackupWorked'))).toBeVisible({ timeout: 180_000 });
    await journey.shot(page, 'add-application-test-backup');
    await form.getByRole('link', { name: t('openApplication') }).click();

    await expect(page).toHaveURL(/\/applications\/[0-9a-f-]{36}$/);
    applicationUrl = new URL(page.url()).pathname;
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(applicationName);
    await expect(page.getByRole('main').getByRole('link', { name, exact: true })).toBeVisible();
    await expect(valueOf(page.getByRole('main'), t('projectFolder'))).toHaveText(SSH.projectDir);
    for (const folder of ALLOWED_FOLDERS) {
      await expect(page.getByRole('listitem').filter({ hasText: folder })).toBeVisible();
    }
    await journey.shot(page, 'application-overview');
  });

  test('the application check finds everything it looks for', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(applicationUrl);
    const main = page.getByRole('main');

    const check = main.getByRole('button', { name: t('checkNow') });
    await check.click();
    await expect(check).toBeDisabled();
    await expect(check).toBeEnabled({ timeout: 120_000 });

    await expect(main.getByText(t('ready')).first()).toBeVisible();
    await expect(valueOf(main, t('system'))).not.toBeEmpty();
    await expect(valueOf(main, t('dbsInApplication'))).toHaveText(/\d+\.\d+/);
    await expect(valueOf(main, t('backupCommand'))).toHaveText(t('found'));
    await expect(valueOf(main, t('envFile'))).toHaveText(t('found'));
    await expect(valueOf(main, t('backupFolder'))).toHaveText(t('found'));
    for (const folder of ALLOWED_FOLDERS) {
      await expect(valueOf(main, folder)).toHaveText(t('found'));
    }
    await journey.shot(page, 'application-checked');
  });

  test('the backup passphrase shows only with the right password', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(applicationUrl);

    await page.getByRole('button', { name: t('showPassphrase') }).click();
    const prompt = page.getByRole('dialog');
    await prompt.getByLabel(t('yourPassword'), { exact: true }).fill('not-the-password');
    await prompt.getByRole('button', { name: t('showPassphrase') }).click();

    await expect(prompt.getByText(t('wrongPassword'))).toBeVisible();
    await expect(prompt.getByLabel(t('yourPassword'), { exact: true })).toHaveAttribute('aria-invalid', 'true');
    await journey.shot(page, 'passphrase-wrong-password');

    await prompt.getByLabel(t('yourPassword'), { exact: true }).fill(ADMIN.password);
    await prompt.getByRole('button', { name: t('showPassphrase') }).click();

    await expect(prompt).toBeHidden();
    const shown = page.getByRole('textbox', { name: t('passphrase'), exact: true });
    await expect(shown).toHaveValue(/.{16,}/);
    await page.getByRole('button', { name: t('hidePassphrase') }).click();
    await expect(shown).toBeHidden();
    await expect(page.getByRole('button', { name: t('showPassphrase') })).toBeVisible();
  });

  test('the host key review finds the pinned key unchanged', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(serverUrl);

    await expect(page.getByRole('main').getByRole('definition').filter({ hasText: /^SHA256:/ })).toHaveText(
      FINGERPRINT,
    );
    await page.getByRole('button', { name: t('reviewHostKey') }).click();
    const review = page.getByRole('dialog');

    await expect(review.getByRole('definition').filter({ hasText: /^SHA256:/ })).toHaveCount(2);
    await expect(review.getByText(t('pinnedUnchanged'))).toBeVisible();
    await journey.shot(page, 'host-key-review');
    await page.keyboard.press('Escape');
    await expect(review).toBeHidden();
  });

  test('removing the application, then deleting the server, each ask for the password', async ({
    page,
    journey,
  }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(applicationUrl);

    await page.getByRole('button', { name: t('removeApplication') }).click();
    const removal = page.getByRole('dialog');
    await expect(removal).toContainText(applicationName);
    await removal.getByLabel(t('yourPassword'), { exact: true }).fill(ADMIN.password);
    await removal.getByRole('button', { name: t('removeApplication') }).click();
    await expect(journey.toast(page, 'applicationRemoved')).toBeVisible();
    expect((await page.request.get(`/api${applicationUrl}/`)).status()).toBe(404);

    await page.goto(serverUrl);
    await page.getByRole('button', { name: t('deleteServer') }).click();
    const prompt = page.getByRole('dialog');
    await expect(prompt).toContainText(name);
    await prompt.getByLabel(t('yourPassword'), { exact: true }).fill(ADMIN.password);
    await prompt.getByRole('button', { name: t('deleteServer') }).click();

    await expect(page).toHaveURL(/\/servers$/);
    await expect(page.getByRole('main').getByRole('link', { name })).toHaveCount(0);
    expect((await page.request.get(`/api${serverUrl}/`)).status()).toBe(404);
  });
});

test.describe('the application page tabs', () => {
  let api: Api;
  let applicationId = '';
  let name = '';

  test.beforeAll(async ({}, testInfo) => {
    api = await Api.signIn(baseUrlOf(testInfo));
    name = `e2e tabs ${testInfo.project.name} ${Date.now().toString(36)}`;
    applicationId = (await api.createServerWithApplication(name)).application.id;
  });

  test.afterAll(async () => {
    await api.deleteServersNamed(name.replace(/ renamed$/, ''));
  });

  test('every tab is a link to that section, and Overview leads back', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(`/applications/${applicationId}`);
    const tabs = page.getByRole('tablist', { name: t('applicationSections') });

    for (const [tab, path] of [
      ['tabBackups', 'backups'],
      ['tabSchedule', 'schedule'],
      ['tabFiles', 'files'],
      ['tabEnv', 'environment'],
      ['tabDeploy', 'deploy'],
      ['tabTerminal', 'terminal'],
      ['tabActivity', 'activity'],
    ] as const) {
      await tabs.getByRole('tab', { name: t(tab) }).click();
      await expect(page).toHaveURL(new RegExp(`/applications/${applicationId}/${path}`));
      await expect(tabs.getByRole('tab', { name: t(tab) })).toHaveAttribute('aria-selected', 'true');
    }

    await tabs.getByRole('tab', { name: t('tabOverview') }).click();

    await expect(page).toHaveURL(new RegExp(`/applications/${applicationId}$`));
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(name);
  });

  test('a rename and a changed path save in place while the server is being set up', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(`/applications/${applicationId}`);
    const dialog = page.getByRole('dialog', { name: t('editApplication') });

    await page.getByRole('button', { name: t('edit'), exact: true }).click();
    name = `${name} renamed`;
    await dialog.getByRole('textbox', { name: t('name'), exact: true }).fill(name);
    await dialog.getByRole('button', { name: t('saveChanges') }).click();

    await expect(dialog).toBeHidden();
    await expect(journey.toast(page, 'changesSaved')).toBeVisible();
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(name);
    await journey.dismissToasts(page);

    // Whoever added the server changes its settings without the password for a while; the backend says when.
    const moved = `${SSH.envPath}.moved`;
    await page.getByRole('button', { name: t('edit'), exact: true }).click();
    await dialog.getByRole('combobox', { name: t('envFile'), exact: true }).fill(moved);
    await dialog.getByRole('button', { name: t('saveChanges') }).click();

    await expect(dialog).toBeHidden();
    await expect(journey.toast(page, 'changesSaved')).toBeVisible();
    await expect(journey.shown(page.getByRole('main'), moved)).toBeVisible();
    await journey.shot(page, 'application-edited');
  });
});
