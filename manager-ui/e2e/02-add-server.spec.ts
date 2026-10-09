import type { Locator, Page } from '@playwright/test';
import { Api } from './support/api';
import { ADMIN, ALLOWED_FOLDERS, SSH } from './support/config';
import { expect, test } from './support/fixtures';
import type { Journey } from './support/fixtures.types';

test.describe.configure({ mode: 'serial' });

const stepIs = async (page: Page, name: string): Promise<void> => {
  await expect(page.getByRole('button', { name: new RegExp(name), expanded: true })).toBeVisible();
};

const fillProject = async (form: Locator, { t }: Journey): Promise<void> => {
  await form.getByRole('combobox', { name: t('projectFolder') }).fill(SSH.projectDir);
  await form.getByRole('combobox', { name: t('pythonCommand') }).fill(SSH.python);
  await form.getByRole('textbox', { name: t('remoteBackupFolder') }).fill(SSH.remoteBackupDir);
  for (const remove of await form.getByRole('button', { name: new RegExp(`^${t('remove')} `) }).all()) {
    await remove.click();
  }
  const folders = form.getByRole('textbox', { name: t('allowedFolders') });
  for (const folder of ALLOWED_FOLDERS) {
    await folders.fill(folder);
    await folders.press('Enter');
  }
  await form.getByRole('textbox', { name: t('envFile') }).fill(SSH.envPath);
};

test.describe('adding a server', () => {
  let name = '';
  let serverUrl = '';

  test.beforeAll(({}, testInfo) => {
    name = `e2e wizard ${testInfo.project.name} ${Date.now().toString(36)}`;
  });

  test.afterAll(async ({}, testInfo) => {
    // Only reached when a step failed before the journey's own delete.
    const api = await Api.signIn(testInfo.project.use.baseURL ?? 'http://localhost:4200');
    for (const server of await api.findServers(name)) await api.deleteServer(server.id);
    await api.dispose();
  });

  test('the first steps report what is missing or out of range', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto('/servers');
    await page.getByRole('main').getByRole('link', { name: t('addServer'), exact: true }).first().click();

    await expect(page).toHaveURL(/\/servers\/new$/);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(t('wizardTitle'));
    const form = page.getByRole('main');
    const next = form.getByRole('button', { name: t('next'), exact: true });
    await stepIs(page, t('stepSnippet'));

    await form.getByRole('textbox', { name: t('stepSnippet') }).fill('not a snippet');
    await next.click();
    await expect(form.getByText(t('snippetInvalid'))).toBeVisible();
    await stepIs(page, t('stepSnippet'));

    await form.getByRole('textbox', { name: t('stepSnippet') }).fill('');
    await next.click();
    await stepIs(page, t('stepAddress'));

    await next.click();
    await expect(form.getByText(t('fillIn'))).toHaveCount(3);
    await expect(form.getByRole('textbox', { name: t('name'), exact: true })).toHaveAccessibleDescription(
      new RegExp(t('fillIn')),
    );
    await expect(form.getByText(t('getHostKeyFirst'))).toBeVisible();

    await form.getByRole('spinbutton', { name: t('port') }).fill('65536');
    await next.click();
    await expect(form.getByRole('spinbutton', { name: t('port') })).toHaveAttribute('aria-invalid', 'true');
    await expect(form.getByText(t('portRange'))).toBeVisible();
    await stepIs(page, t('stepAddress'));
    await journey.shot(page, 'add-server-validation');
  });

  test('the wizard adds a server, checks it and takes a test backup', async ({ page, journey }) => {
    test.setTimeout(300_000);
    const { t } = journey;
    await journey.signIn(page);
    await page.goto('/servers/new');
    const form = page.getByRole('main');
    const next = form.getByRole('button', { name: t('next'), exact: true });

    await next.click();
    await stepIs(page, t('stepAddress'));
    await form.getByRole('textbox', { name: t('name'), exact: true }).fill(name);
    await form.getByRole('textbox', { name: t('host'), exact: true }).fill(SSH.host);
    await form.getByRole('spinbutton', { name: t('port') }).fill(String(SSH.port));
    await form.getByRole('textbox', { name: t('username') }).fill(SSH.username);
    await form.getByRole('button', { name: t('getHostKey') }).click();
    await expect(form.getByRole('definition').filter({ hasText: /^SHA256:/ })).toHaveText(SSH.fingerprint);
    await journey.shot(page, 'add-server-host-key');

    await next.click();
    await expect(form.getByText(t('compareFirst'))).toBeVisible();
    const match = form.getByRole('checkbox', { name: t('fingerprintsMatch') });
    await match.click();
    await expect(match).toBeChecked();
    await next.click();

    await stepIs(page, t('stepSignIn'));
    const passwordMethod = form.getByRole('radio', { name: t('password'), exact: true });
    await passwordMethod.click();
    await expect(passwordMethod).toBeChecked();
    await form.getByLabel(t('serverPassword'), { exact: true }).fill(SSH.password);
    await form.getByRole('button', { name: t('addServerSubmit'), exact: true }).click();

    await stepIs(page, t('stepProject'));
    await expect(form.getByText(t('serverAdded'))).toBeVisible();
    await form.getByRole('button', { name: t('findProject') }).click();
    await expect(form.getByRole('button', { name: t('findProject') })).toBeEnabled({ timeout: 60_000 });
    await fillProject(form, journey);
    await journey.shot(page, 'add-server-project');
    await next.click();

    await stepIs(page, t('stepCheck'));
    await form.getByRole('button', { name: t('checkNow') }).click();
    await expect(form.getByText(t('versionsWork'))).toBeVisible({ timeout: 120_000 });
    await journey.shot(page, 'add-server-check');
    await next.click();

    await stepIs(page, t('stepPassphrase'));
    await form.getByRole('button', { name: t('readPassphrase') }).click();
    await expect(form.getByText(t('passphraseSaved'))).toBeVisible({ timeout: 60_000 });
    await next.click();

    await stepIs(page, t('stepTestBackup'));
    await form.getByRole('button', { name: t('takeTestBackup') }).click();
    await expect(form.getByText(t('testBackupWorked'))).toBeVisible({ timeout: 180_000 });
    await journey.shot(page, 'add-server-test-backup');
    await form.getByRole('link', { name: t('openServer') }).click();

    await expect(page).toHaveURL(/\/servers\/[0-9a-f-]{36}$/);
    serverUrl = new URL(page.url()).pathname;
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(name);
    await expect(page.getByRole('main')).toContainText(`${SSH.username}@${SSH.host}:${SSH.port}`);
    const pinned = page.getByRole('definition').filter({ hasText: /^SHA256:/ });
    await expect(pinned).toHaveText(SSH.fingerprint);
    for (const folder of ALLOWED_FOLDERS) {
      await expect(page.getByRole('listitem').filter({ hasText: folder })).toBeVisible();
    }
    await journey.shot(page, 'server-overview');
  });

  test('the connection check finds everything it looks for', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(serverUrl);

    const check = page.getByRole('button', { name: t('checkNow') });
    await check.click();
    await expect(check).toBeDisabled();
    await expect(check).toBeEnabled({ timeout: 120_000 });
    await expect(check).toBeEnabled({ timeout: 120_000 });

    await expect(page.getByRole('main').getByText(t('ready')).first()).toBeVisible();
    const valueOf = (term: string) =>
      page.getByRole('term').filter({ hasText: term }).first().locator('xpath=following-sibling::*[1]');
    await expect(valueOf(t('system'))).not.toBeEmpty();
    await expect(valueOf(t('dbsVersion'))).toHaveText(/\d+\.\d+/);
    await expect(valueOf(t('backupCommand'))).toHaveText(t('found'));
    await expect(valueOf(t('envFile'))).toHaveText(t('found'));
    await expect(valueOf(t('remoteBackupFolder'))).toHaveText(t('found'));
    for (const folder of ALLOWED_FOLDERS) {
      await expect(valueOf(folder)).toHaveText(t('found'));
    }
    await journey.shot(page, 'server-checked');
  });

  test('the backup passphrase shows only with the right password', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(serverUrl);

    await page.getByRole('button', { name: t('showPassphrase') }).click();
    const prompt = page.getByRole('dialog');
    await prompt.getByLabel(t('yourPassword'), { exact: true }).fill('not-the-password');
    await prompt.getByRole('button', { name: t('showPassphrase') }).click();

    await expect(prompt.getByText(t('wrongPassword'))).toBeVisible();
    await expect(prompt.getByLabel(t('yourPassword'), { exact: true })).toHaveAttribute('aria-invalid', 'true');
    await journey.shot(page, 'passphrase-wrong-password');

    await prompt.getByLabel(t('yourPassword'), { exact: true }).fill('journey-admin-pass');
    await prompt.getByRole('button', { name: t('showPassphrase') }).click();

    await expect(prompt).toBeHidden();
    const shown = page.getByRole('textbox', { name: t('passphrase'), exact: true });
    await expect(shown).toHaveValue(/.{16,}/);
    await journey.shot(page, 'passphrase-shown');
    await page.getByRole('button', { name: t('hidePassphrase') }).click();
    await expect(shown).toBeHidden();
    await expect(page.getByRole('button', { name: t('showPassphrase') })).toBeVisible();
  });

  test('the host key review finds the pinned key unchanged', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(serverUrl);

    await page.getByRole('button', { name: t('reviewHostKey') }).click();
    const review = page.getByRole('dialog');

    await expect(review.getByRole('definition').filter({ hasText: /^SHA256:/ })).toHaveCount(2);
    await expect(review.getByRole('status')).toBeVisible();
    await journey.shot(page, 'host-key-review');
    await page.keyboard.press('Escape');
    await expect(review).toBeHidden();
  });

  test('deleting the server asks first, then it is gone', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(serverUrl);

    await page.getByRole('button', { name: t('deleteServer') }).click();
    const confirm = page.getByRole('alertdialog');
    await expect(confirm.getByRole('heading', { level: 2 })).toContainText(name);
    await confirm.getByRole('button', { name: t('deleteServer') }).click();

    await expect(page).toHaveURL(/\/servers$/);
    await expect(page.getByRole('main').getByRole('link', { name })).toHaveCount(0);
    expect((await page.request.get(`/api${serverUrl}/`)).status()).toBe(404);
  });
});

test.describe('the server page tabs', () => {
  let api: Api;
  let serverId = '';
  let name = '';

  test.beforeAll(async ({}, testInfo) => {
    api = await Api.signIn(testInfo.project.use.baseURL ?? 'http://localhost:4200');
    name = `e2e tabs ${testInfo.project.name} ${Date.now().toString(36)}`;
    serverId = (await api.createServer(name)).id;
  });

  test.afterAll(async () => {
    await api.deleteServer(serverId);
    await api.dispose();
  });

  test('every tab is a link to that section, and Overview leads back', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(`/servers/${serverId}`);
    const tabs = page.getByRole('tablist', { name: t('serverSections') });

    for (const [tab, path] of [
      ['tabBackups', 'backups'],
      ['tabFiles', 'files'],
      ['tabEnv', 'environment'],
      ['tabActivity', 'activity'],
    ] as const) {
      await tabs.getByRole('tab', { name: t(tab) }).click();
      await expect(page).toHaveURL(new RegExp(`/servers/${serverId}/${path}`));
      await expect(tabs.getByRole('tab', { name: t(tab) })).toHaveAttribute('aria-selected', 'true');
    }

    await tabs.getByRole('tab', { name: t('tabOverview') }).click();

    await expect(page).toHaveURL(new RegExp(`/servers/${serverId}$`));
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(name);
  });

  test('a rename saves as it is, and a changed path asks for your password', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(`/servers/${serverId}`);
    const dialog = page.getByRole('dialog');
    const password = dialog.getByLabel(t('yourPassword'), { exact: true });

    await page.getByRole('button', { name: t('edit'), exact: true }).click();
    name = `${name} renamed`;
    await dialog.getByRole('textbox', { name: t('name'), exact: true }).fill(name);
    await dialog.getByRole('button', { name: t('next') }).click();
    await expect(password).toHaveCount(0);
    await dialog.getByRole('button', { name: t('saveChanges') }).click();

    await expect(journey.toast(page, 'changesSaved')).toBeVisible();
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(name);
    await journey.dismissToasts(page);

    await page.getByRole('button', { name: t('edit'), exact: true }).click();
    await dialog.getByRole('button', { name: t('next') }).click();
    await dialog.getByRole('textbox', { name: t('envFile'), exact: true }).fill('/srv/e2e-app/.env.moved');
    await expect(password).toBeVisible();
    await dialog.getByRole('button', { name: t('saveChanges') }).click();
    await expect(dialog.getByText(t('enterPassword'))).toBeVisible();

    await password.fill('not-the-password');
    await dialog.getByRole('button', { name: t('saveChanges') }).click();
    await expect(dialog.getByText(t('wrongPassword'))).toBeVisible();
    await journey.shot(page, 'server-edit-wrong-password');

    await password.fill(ADMIN.password);
    await dialog.getByRole('button', { name: t('saveChanges') }).click();

    await expect(dialog).toBeHidden();
    await expect(journey.toast(page, 'changesSaved')).toBeVisible();
    await expect(journey.shown(page, '/srv/e2e-app/.env.moved')).toBeVisible();
  });
});
