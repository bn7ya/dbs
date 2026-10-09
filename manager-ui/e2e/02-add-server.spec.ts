import { Api } from './support/api';
import { ADMIN, ALLOWED_FOLDERS, SSH } from './support/config';
import { expect, test } from './support/fixtures';

test.describe.configure({ mode: 'serial' });

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

  test('the connection step reports what is missing or out of range', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    const opener = page.getByRole('main').getByRole('button', { name: t('addServer'), exact: true }).first();
    await opener.click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { level: 2 })).toHaveText(t('addServer'));

    await dialog.getByRole('button', { name: t('next'), exact: true }).click();

    await expect(dialog.getByText(t('fillIn'))).toHaveCount(4);
    await expect(dialog.getByRole('textbox', { name: t('name'), exact: true })).toHaveAttribute('aria-invalid', 'true');
    await expect(dialog.getByRole('tab', { name: t('stepConnection') })).toHaveAttribute('aria-selected', 'true');

    // One past the highest port: the field keeps it inside the range rather than saying so.
    await dialog.getByRole('spinbutton', { name: t('port') }).fill('65536');
    await dialog.getByRole('button', { name: t('next'), exact: true }).click();
    await expect(dialog.getByRole('spinbutton', { name: t('port') })).toHaveValue('65535');
    await expect(dialog.getByRole('tab', { name: t('stepConnection') })).toHaveAttribute('aria-selected', 'true');
    await journey.shot(page, 'add-server-validation');

    // A dialog traps focus and gives it back to what opened it.
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    await expect(opener).toBeFocused();
  });

  test('the wizard pins the host key only once its fingerprint is compared', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.getByRole('main').getByRole('button', { name: t('addServer'), exact: true }).first().click();
    const dialog = page.getByRole('dialog');

    await dialog.getByRole('textbox', { name: t('name'), exact: true }).fill(name);
    await dialog.getByRole('textbox', { name: t('host'), exact: true }).fill(SSH.host);
    await dialog.getByRole('spinbutton', { name: t('port') }).fill(String(SSH.port));
    await dialog.getByRole('textbox', { name: t('username') }).fill(SSH.username);
    const passwordMethod = dialog.getByRole('radio', { name: t('password'), exact: true });
    await passwordMethod.click();
    await expect(passwordMethod).toBeChecked();
    await dialog.getByRole('textbox', { name: t('serverPassword'), exact: true }).fill(SSH.password);
    await dialog.getByRole('button', { name: t('next'), exact: true }).click();

    await expect(dialog.getByRole('tab', { name: t('stepHostKey') })).toHaveAttribute('aria-selected', 'true');
    await dialog.getByRole('button', { name: t('next'), exact: true }).click();
    await expect(dialog.getByRole('alert')).toHaveText(t('getHostKeyFirst'));

    await dialog.getByRole('button', { name: t('getHostKey') }).click();

    const shown = dialog.getByRole('definition').filter({ hasText: /^SHA256:/ });
    await expect(shown).toHaveText(SSH.fingerprint);
    await expect(dialog.getByRole('definition').filter({ hasText: /^ssh-/ })).toBeVisible();
    await journey.shot(page, 'add-server-host-key');

    await dialog.getByRole('button', { name: t('next'), exact: true }).click();
    await expect(dialog.getByText(t('compareFirst'))).toBeVisible();
    const match = dialog.getByRole('checkbox', { name: t('fingerprintsMatch') });
    await match.click();
    await expect(match).toBeChecked();
    await dialog.getByRole('button', { name: t('next'), exact: true }).click();

    await expect(dialog.getByRole('tab', { name: t('stepDjango') })).toHaveAttribute('aria-selected', 'true');
    await dialog.getByRole('textbox', { name: t('projectFolder') }).fill(SSH.projectDir);
    await dialog.getByRole('textbox', { name: t('pythonCommand') }).fill(SSH.python);
    await dialog.getByRole('textbox', { name: t('remoteBackupFolder') }).fill(SSH.remoteBackupDir);
    const folders = dialog.getByRole('textbox', { name: t('allowedFolders') });
    for (const folder of ALLOWED_FOLDERS) {
      await folders.fill(folder);
      await folders.press('Enter');
    }
    await dialog.getByRole('textbox', { name: t('envFile') }).fill(SSH.envPath);
    await journey.shot(page, 'add-server-settings');
    await dialog.getByRole('button', { name: t('addServerSubmit'), exact: true }).click();

    await expect(page).toHaveURL(/\/servers\/[0-9a-f-]{36}$/);
    serverUrl = new URL(page.url()).pathname;
    await expect(journey.toast(page, 'serverAdded')).toBeVisible();
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(name);
    await expect(page.getByRole('main')).toContainText(`${SSH.username}@${SSH.host}:${SSH.port}`);
    await expect(page.getByRole('main').getByText(t('notChecked')).first()).toBeVisible();
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
    await expect(check).toHaveAttribute('aria-disabled', 'true');
    await expect(check).toBeEnabled({ timeout: 120_000 });
    await expect(check).not.toHaveAttribute('aria-disabled', 'true', { timeout: 120_000 });

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
    await prompt.getByRole('textbox', { name: t('yourPassword') }).fill('not-the-password');
    await prompt.getByRole('button', { name: t('showPassphrase') }).click();

    await expect(prompt.getByText(t('wrongPassword'))).toBeVisible();
    await expect(prompt.getByRole('textbox', { name: t('yourPassword') })).toHaveAttribute('aria-invalid', 'true');
    await journey.shot(page, 'passphrase-wrong-password');

    await prompt.getByRole('textbox', { name: t('yourPassword') }).fill('journey-admin-pass');
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
    const tabs = page.getByRole('navigation', { name: t('serverSections') });

    for (const [tab, path] of [
      ['tabBackups', 'backups'],
      ['tabFiles', 'files'],
      ['tabEnv', 'environment'],
      ['tabActivity', 'activity'],
    ] as const) {
      await tabs.getByRole('link', { name: t(tab) }).click();
      await expect(page).toHaveURL(new RegExp(`/servers/${serverId}/${path}`));
      await expect(tabs.getByRole('link', { name: t(tab) })).toHaveAttribute('aria-current', 'page');
    }

    await tabs.getByRole('link', { name: t('tabOverview') }).click();

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
