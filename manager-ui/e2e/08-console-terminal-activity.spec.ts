import type { Page } from '@playwright/test';
import { Api } from './support/api';
import { ADMIN, SSH } from './support/config';
import type { CopyKey } from './support/copy.types';
import { baseUrlOf, expect, test } from './support/fixtures';
import type { Journey } from './support/fixtures.types';
import { acquireLock } from './support/lock';

test.describe.configure({ mode: 'serial' });

test.describe('a developer drives the manager from its console', () => {
  let api: Api;
  let name = '';
  let applicationId = '';
  let planName = '';

  test.beforeAll(async ({}, testInfo) => {
    api = await Api.signIn(baseUrlOf(testInfo));
    name = `e2e console ${testInfo.project.name} ${Date.now().toString(36)}`;
    planName = `${name} media`;
    applicationId = (await api.createServerWithApplication(name)).application.id;
    await api.capturePassphrase(applicationId);
  });

  test.afterAll(async () => {
    await api.deleteServersNamed(name);
  });

  test('app list prints every application, ours among them', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.getByRole('navigation', { name: /.+/ }).first().getByRole('link', { name: t('navConsole') }).click();

    await expect(page).toHaveURL(/\/console$/);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(t('consoleTitle'));
    const command = page.getByRole('textbox', { name: t('command') });
    await command.fill('app list');
    await command.press('Enter');

    const log = page.getByRole('log', { name: t('consoleLog') });
    await expect(log).toContainText('django_dbs app list');
    await expect(log).toContainText(name);
    await expect(log).toContainText(applicationId);
    await expect(log).toContainText(journey.say('consoleDone', { code: '0' }));
    await expect(command).toHaveValue('');
    await journey.shot(page, 'console-app-list');
  });

  test('a command that acts for real asks for the password, and runs with it', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto('/console');
    const command = page.getByRole('textbox', { name: t('command') });
    await command.fill(`plan add "${name}" "${planName}" --kind archive --path ${SSH.mediaDir} --manual`);
    await command.press('Enter');

    const prompt = page.getByRole('dialog', { name: t('consolePasswordTitle') });
    await expect(prompt).toContainText(planName);
    await prompt.getByLabel(t('yourPassword'), { exact: true }).fill('not-the-password');
    await prompt.getByRole('button', { name: t('consoleRunIt') }).click();
    await expect(prompt.getByText(t('wrongPassword'))).toBeVisible();
    await journey.shot(page, 'console-password');
    await prompt.getByLabel(t('yourPassword'), { exact: true }).fill(ADMIN.password);
    await prompt.getByRole('button', { name: t('consoleRunIt') }).click();

    await expect(prompt).toBeHidden();
    const log = page.getByRole('log', { name: t('consoleLog') });
    await expect(log).toContainText(`Added the plan ${planName}.`);
    expect((await api.plans(applicationId)).map((plan) => plan.name)).toContain(planName);
  });

  test('a backup the console starts is followed until it ends', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto('/console');
    const command = page.getByRole('textbox', { name: t('command') });
    await command.fill(`backup take "${name}"`);
    await command.press('Enter');

    const log = page.getByRole('log', { name: t('consoleLog') });
    const job = log.getByRole('listitem').filter({ hasText: journey.say('consoleJob', { id: '' }) }).last();
    await expect(job).toContainText(t('jobSucceeded'), { timeout: 180_000 });
    await expect(job.getByRole('link', { name: t('followActivity') })).toHaveAttribute('href', '/activity');
    await journey.shot(page, 'console-job');
    expect(await api.backups(applicationId)).toHaveLength(1);

    await command.press('ArrowUp');
    await expect(command).toHaveValue(`backup take "${name}"`);
  });
});

test.describe('a developer opens a shell on the server from the manager', () => {
  let api: Api;
  let name = '';
  let serverId = '';
  let release: () => void = () => undefined;

  test.beforeAll(async ({}, testInfo) => {
    // An account may hold two terminals at a time; both projects open theirs one after the other.
    release = await acquireLock('terminal');
    api = await Api.signIn(baseUrlOf(testInfo));
    await api.closeTerminals();
    name = `e2e terminal ${testInfo.project.name} ${Date.now().toString(36)}`;
    serverId = (await api.createServer(name)).id;
  });

  test.afterAll(async () => {
    await api.closeTerminals();
    await api.deleteServersNamed(name);
    release();
  });

  test('a shell on the server answers what is typed, and closes', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(`/servers/${serverId}`);
    const tabs = page.getByRole('tablist', { name: t('serverSections') });
    await tabs.getByRole('tab', { name: t('tabServerTerminal') }).click();
    await expect(page).toHaveURL(new RegExp(`/servers/${serverId}/terminal$`));
    const main = page.getByRole('main');
    await expect(main).toContainText(SSH.username);

    await main.getByRole('button', { name: t('openTerminal') }).click();
    const prompt = page.getByRole('dialog');
    await prompt.getByLabel(t('yourPassword'), { exact: true }).fill(ADMIN.password);
    await prompt.getByRole('button', { name: t('openTheTerminal') }).click();
    await expect(prompt).toBeHidden();

    // The view's name isolates the server's name, so it is matched on the name alone.
    const shell = main.getByRole('group', { name: new RegExp(name) });
    await expect(main.getByRole('button', { name: t('closeTerminal') })).toBeVisible({ timeout: 60_000 });
    await expect(shell).toContainText('$', { timeout: 60_000 });
    await shell.getByRole('textbox').focus();
    await page.keyboard.type('echo $((6*7))');
    await page.keyboard.press('Enter');

    await expect(shell.getByRole('listitem').filter({ hasText: /^42\s*$/ })).toBeVisible({ timeout: 30_000 });
    await journey.shot(page, 'terminal');

    await main.getByRole('button', { name: t('closeTerminal') }).click();
    await expect(main.getByText(t('terminalClosed'))).toBeVisible({ timeout: 30_000 });
    await expect(main.getByRole('button', { name: t('openTerminal') })).toBeVisible();
    expect((await page.request.get('/api/terminals/')).ok()).toBe(true);
  });
});

const pick = async (page: Page, { t }: Journey, filter: CopyKey, option: CopyKey): Promise<void> => {
  const select = page.getByRole('main').getByRole('combobox', { name: t(filter) });
  await select.click();
  await page.getByRole('option', { name: t(option), exact: true }).click();
  await expect(select).toContainText(t(option));
};

test.describe('a developer reads back what happened, in words, filtered by action and status', () => {
  let api: Api;
  let serverId = '';
  let applicationId = '';
  let name = '';
  let applicationName = '';

  test.beforeAll(async ({}, testInfo) => {
    api = await Api.signIn(baseUrlOf(testInfo));
    name = `e2e activity ${testInfo.project.name} ${Date.now().toString(36)}`;
    applicationName = `${name} app`;
    const server = await api.createServer(name);
    serverId = server.id;
    applicationId = (await api.createApplication(serverId, applicationName)).id;
  });

  test.afterAll(async () => {
    await api.deleteServersNamed(name);
  });

  test('a check and a refused passphrase are recorded', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(`/servers/${serverId}`);
    const serverCheck = page.getByRole('main').getByRole('button', { name: t('checkNow') });
    await serverCheck.click();
    await expect(serverCheck).toBeEnabled({ timeout: 120_000 });

    await page.goto(`/applications/${applicationId}`);
    const check = page.getByRole('main').getByRole('button', { name: t('checkNow') });
    await check.click();
    await expect(check).toBeEnabled({ timeout: 120_000 });
    await expect(page.getByRole('main').getByText(t('ready')).first()).toBeVisible();

    await page.getByRole('button', { name: t('showPassphrase') }).click();
    const prompt = page.getByRole('dialog');
    await prompt.getByLabel(t('yourPassword'), { exact: true }).fill('not-the-password');
    await prompt.getByRole('button', { name: t('showPassphrase') }).click();
    await expect(prompt.getByText(t('wrongPassword'))).toBeVisible();
    await page.keyboard.press('Escape');
  });

  test('the global list names each action in words, and the action filter finds ours', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto('/activity');
    const main = page.getByRole('main');

    await expect(page.getByRole('heading', { level: 1 })).toHaveText(t('activityTitle'));
    await expect(main.getByRole('link', { name: applicationName, exact: true }).first()).toBeVisible();
    // A code the bundles do not know would render as itself: none may.
    const code = /\b(auth|server|application|backup|plan|files|env|console|shell|deploy|redeploy)\.[a-z_]+\b/;
    await expect(main.getByText(code)).toHaveCount(0);
    await journey.shot(page, 'activity');

    await pick(page, journey, 'action', 'actionSignIn');
    await expect(journey.shown(main, t('actionSignIn')).first()).toBeVisible();
    await expect(journey.shown(main, t('actionApplicationCheck'))).toHaveCount(0);

    await pick(page, journey, 'action', 'actionApplicationCheck');
    await expect(journey.shown(main, t('actionApplicationCheck')).first()).toBeVisible();
    await expect(journey.shown(main, t('actionSignIn'))).toHaveCount(0);
    await expect(main.getByRole('link', { name: applicationName, exact: true }).first()).toBeVisible();
    await expect(main.getByRole('link', { name, exact: true }).first()).toBeVisible();

    await pick(page, journey, 'action', 'actionShowPassphrase');
    await expect(main.getByRole('link', { name: applicationName, exact: true }).first()).toBeVisible();
    await expect(main.getByText(t('wrongPassword')).filter({ visible: true }).first()).toBeVisible();
  });

  test('filtering by status keeps only the failed entries', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto('/activity');
    const main = page.getByRole('main');
    await expect(journey.shown(main, t('succeeded')).first()).toBeVisible();

    await pick(page, journey, 'status', 'failed');
    await expect(journey.shown(main, t('succeeded'))).toHaveCount(0);
    await expect(journey.shown(main, t('failed')).first()).toBeVisible();
    await journey.shot(page, 'activity-failed');

    await pick(page, journey, 'action', 'actionShowPassphrase');
    await expect(main.getByRole('link', { name: applicationName, exact: true }).first()).toBeVisible();
    await expect(journey.shown(main, t('succeeded'))).toHaveCount(0);
  });

  test("the application's tab shows that application's entries only", async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(`/applications/${applicationId}/activity`);
    const main = page.getByRole('main');

    await expect(journey.shown(main, t('actionApplicationCheck')).first()).toBeVisible();
    await expect(journey.shown(main, t('actionShowPassphrase')).first()).toBeVisible();
    await expect(journey.shown(main, t('actionAddApplication')).first()).toBeVisible();
    await expect(journey.shown(main, t('actionConnectionCheck'))).toHaveCount(0);
    await expect(journey.shown(main, t('actionAddServer'))).toHaveCount(0);
    await expect(journey.shown(main, t('actionSignIn'))).toHaveCount(0);
    await journey.shot(page, 'application-activity');
  });

  test("the server's tab shows the server's entries and its application's", async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(`/servers/${serverId}/activity`);
    const main = page.getByRole('main');

    await expect(journey.shown(main, t('actionConnectionCheck')).first()).toBeVisible();
    await expect(journey.shown(main, t('actionAddServer')).first()).toBeVisible();
    await expect(journey.shown(main, t('actionApplicationCheck')).first()).toBeVisible();
    await expect(journey.shown(main, t('actionShowPassphrase')).first()).toBeVisible();
    await expect(journey.shown(main, t('actionSignIn'))).toHaveCount(0);
    await expect(journey.shown(main, t('actionFailedSignIn'))).toHaveCount(0);
    await expect(main.getByRole('link').filter({ hasText: /^e2e / }).filter({ hasNotText: name })).toHaveCount(0);
    await journey.shot(page, 'server-activity');
  });
});
