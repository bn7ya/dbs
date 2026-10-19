import type { Page } from '@playwright/test';
import { Api } from './support/api';
import { baseUrlOf, expect, test } from './support/fixtures';
import type { CopyKey } from './support/copy.types';
import type { Journey } from './support/fixtures.types';

test.describe.configure({ mode: 'serial' });

const pick = async (page: Page, { t }: Journey, filter: CopyKey, option: CopyKey): Promise<void> => {
  const select = page.getByRole('main').getByRole('combobox', { name: t(filter) });
  await select.click();
  await page.getByRole('option', { name: t(option), exact: true }).click();
  await expect(select).toContainText(t(option));
};

test.describe('activity', () => {
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
