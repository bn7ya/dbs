import { Api } from './support/api';
import { expect, test } from './support/fixtures';
import type { CopyKey } from './support/copy.types';

test.describe.configure({ mode: 'serial' });

test.describe('activity', () => {
  let api: Api;
  let serverId = '';
  let name = '';

  test.beforeAll(async ({}, testInfo) => {
    api = await Api.signIn(testInfo.project.use.baseURL ?? 'http://localhost:4200');
    name = `e2e activity ${testInfo.project.name} ${Date.now().toString(36)}`;
    serverId = (await api.createServer(name)).id;
  });

  test.afterAll(async () => {
    await api.deleteServer(serverId);
    await api.dispose();
  });

  test('a check and a refused passphrase are recorded', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(`/servers/${serverId}`);

    const check = page.getByRole('button', { name: t('checkNow') });
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
    await expect(journey.shown(main, t('actionSignIn')).first()).toBeVisible();
    // A code the bundles do not know would render as itself: none may.
    await expect(main.getByText(/\b(auth|server|backup|plan|files|env)\.[a-z_]+\b/)).toHaveCount(0);
    await expect(main.getByText(/\b[a-z]+\.[a-z]+\.[a-z_.]+\b/)).toHaveCount(0);
    await journey.shot(page, 'activity');

    const pick = async (action: CopyKey) => {
      await page.getByRole('combobox', { name: t('action') }).click();
      await page.getByRole('option', { name: t(action), exact: true }).click();
      await expect(page.getByRole('combobox', { name: t('action') })).toContainText(t(action));
    };

    await pick('actionConnectionCheck');
    await expect(journey.shown(main, t('actionConnectionCheck')).first()).toBeVisible();
    await expect(journey.shown(main, t('actionSignIn'))).toHaveCount(0);
    await expect(main.getByRole('link', { name }).first()).toBeVisible();

    await pick('actionShowPassphrase');
    await expect(main.getByRole('link', { name }).first()).toBeVisible();
    await expect(main.getByText(t('wrongPassword')).filter({ visible: true }).first()).toBeVisible();
  });

  test('filtering by status keeps only the failed entries', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto('/activity');
    const main = page.getByRole('main');
    await expect(journey.shown(main, t('succeeded')).first()).toBeVisible();

    await page.getByRole('combobox', { name: t('status') }).click();
    await page.getByRole('option', { name: t('failed'), exact: true }).click();

    await expect(page.getByRole('combobox', { name: t('status') })).toContainText(t('failed'));
    await expect(journey.shown(main, t('succeeded'))).toHaveCount(0);
    await expect(journey.shown(main, t('failed')).first()).toBeVisible();
    await journey.shot(page, 'activity-failed');

    await page.getByRole('combobox', { name: t('action') }).click();
    await page.getByRole('option', { name: t('actionShowPassphrase'), exact: true }).click();

    await expect(main.getByRole('link', { name }).first()).toBeVisible();
    await expect(journey.shown(main, t('succeeded'))).toHaveCount(0);
  });

  test("the server's tab shows that server's entries only", async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(`/servers/${serverId}/activity`);
    const main = page.getByRole('main');

    await expect(journey.shown(main, t('actionConnectionCheck')).first()).toBeVisible();
    await expect(journey.shown(main, t('actionShowPassphrase')).first()).toBeVisible();
    await expect(journey.shown(main, t('actionAddServer')).first()).toBeVisible();
    await expect(journey.shown(main, t('actionSignIn'))).toHaveCount(0);
    await expect(journey.shown(main, t('actionFailedSignIn'))).toHaveCount(0);
    await expect(main.getByRole('link').filter({ hasText: /^e2e / }).filter({ hasNotText: name })).toHaveCount(0);
    await journey.shot(page, 'server-activity');
  });
});
