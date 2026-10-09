import { Api } from './support/api';
import { ADMIN, SSH } from './support/config';
import { expect, test } from './support/fixtures';
import { acquireLock } from './support/lock';
import { appendRemote, readRemote, remoteReachable, writeRemote } from './support/ssh-fs';

test.describe.configure({ mode: 'serial' });

test.describe('the .env file', () => {
  let api: Api;
  let serverId = '';
  let envUrl = '';
  let original: Buffer | null = null;
  let release: () => void = () => undefined;
  let addedKey = '';

  test.beforeAll(async ({}, testInfo) => {
    release = await acquireLock('envfile');
    api = await Api.signIn(testInfo.project.use.baseURL ?? 'http://localhost:4200');
    original = readRemote(SSH.envPath);
    const server = await api.createServer(`e2e env ${testInfo.project.name} ${Date.now().toString(36)}`);
    serverId = server.id;
    envUrl = `/servers/${serverId}/environment`;
    addedKey = `E2E_${testInfo.project.name.toUpperCase()}_${Date.now().toString(36).toUpperCase()}`;
  });

  test.afterAll(async () => {
    if (original) writeRemote(SSH.envPath, original);
    await api.deleteServer(serverId);
    await api.dispose();
    release();
  });

  const keysOf = (content: Buffer | null): string[] =>
    (content?.toString('utf8') ?? '')
      .split('\n')
      .filter((line) => /^[A-Z_][A-Z0-9_]*=/.test(line))
      .map((line) => line.split('=')[0]);

  test('Pull now keeps the first version, key names shown and values masked', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(envUrl);

    await expect(page.getByRole('heading', { name: t('noVersionsYet') })).toBeVisible();
    await expect(page.getByRole('main')).toContainText(SSH.envPath);
    await journey.shot(page, 'env-empty');

    await page.getByRole('button', { name: t('pullNow') }).click();

    await expect(journey.toast(page, 'newVersionKept')).toBeVisible();
    await expect(page.getByRole('heading', { name: t('selectedVersion') })).toBeVisible();
    await expect(page.getByText(t('firstVersion'))).toBeVisible();
    const keys = keysOf(original);
    for (const key of keys.length ? keys : ['SECRET_KEY']) {
      await expect(page.getByRole('term').filter({ hasText: key })).toBeVisible();
    }
    const masked = page.getByRole('img', { name: t('valueHidden') });
    await expect(masked.first()).toBeVisible();
    if (keys.length) await expect(masked).toHaveCount(keys.length);
    await expect(page.getByRole('main')).not.toContainText('SECRET_KEY=');
    await journey.shot(page, 'env-pulled');
  });

  test('Show values asks for the password; Hide masks them again', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(envUrl);

    await page.getByRole('button', { name: t('showValues') }).click();
    const prompt = page.getByRole('dialog');
    await prompt.getByRole('textbox', { name: t('yourPassword') }).fill('not-the-password');
    await prompt.getByRole('button', { name: t('showValues') }).click();
    await expect(prompt.getByText(t('wrongPassword'))).toBeVisible();

    await prompt.getByRole('textbox', { name: t('yourPassword') }).fill(ADMIN.password);
    await prompt.getByRole('button', { name: t('showValues') }).click();

    await expect(prompt).toBeHidden();
    const content = page.getByRole('textbox', { name: t('fileContent') });
    await expect(content).toBeVisible();
    if (original) {
      expect((await content.inputValue()).replace(/\r\n/g, '\n')).toBe(original.toString('utf8'));
    } else {
      await expect(content).toHaveValue(/=/);
    }
    await journey.shot(page, 'env-revealed');

    await page.getByRole('button', { name: t('hideValues') }).click();

    await expect(content).toBeHidden();
    await expect(page.getByRole('img', { name: t('valueHidden') }).first()).toBeVisible();
  });

  test('pulling again with no change keeps nothing new', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(envUrl);
    const rows = page.getByRole('table').getByRole('button');
    await expect(rows).toHaveCount(1);

    await page.getByRole('button', { name: t('pullNow') }).click();

    await expect(journey.toast(page, 'noChange')).toBeVisible();
    await expect(rows).toHaveCount(1);
  });

  test('a change on the server pulls as a new version that compares with the previous', async ({ page, journey }) => {
    test.skip(!remoteReachable, 'E2E_SSH_FS is empty: the server file cannot be changed from here');
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(envUrl);
    appendRemote(SSH.envPath, `${addedKey}=1\n`);

    await page.getByRole('button', { name: t('pullNow') }).click();

    await expect(journey.toast(page, 'newVersionKept')).toBeVisible();
    await expect(page.getByRole('table').getByRole('button')).toHaveCount(2);
    await expect(page.getByRole('term').filter({ hasText: addedKey })).toBeVisible();

    await page.getByRole('button', { name: t('compare') }).click();

    await expect(page.getByRole('heading', { name: t('changesSince') })).toBeVisible();
    await expect(page.getByRole('term').filter({ hasText: t('addedKeys') })).toBeVisible();
    await expect(page.getByRole('listitem').filter({ hasText: addedKey })).toBeVisible();
    await journey.shot(page, 'env-compare');
  });

  test('pushing the earlier version back restores the file byte for byte', async ({ page, journey }) => {
    test.skip(!remoteReachable, 'E2E_SSH_FS is empty: the server file cannot be read from here');
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(envUrl);
    await page.getByRole('table').getByRole('button').nth(1).click();
    await expect(page.getByRole('term').filter({ hasText: addedKey })).toHaveCount(0);

    await page.getByRole('button', { name: t('pushThis') }).click();
    const confirm = page.getByRole('alertdialog');
    await expect(confirm.getByRole('heading', { level: 2 })).toHaveText(t('replaceEnv'));
    await expect(confirm).toContainText(SSH.envPath);
    await confirm.getByRole('button', { name: t('continue') }).click();

    const prompt = page.getByRole('dialog');
    await prompt.getByRole('textbox', { name: t('yourPassword') }).fill('not-the-password');
    await prompt.getByRole('button', { name: t('pushVersion') }).click();
    await expect(prompt.getByText(t('wrongPassword'))).toBeVisible();
    await journey.shot(page, 'env-push-wrong-password');
    await prompt.getByRole('textbox', { name: t('yourPassword') }).fill(ADMIN.password);
    await prompt.getByRole('button', { name: t('pushVersion') }).click();

    await expect(journey.toast(page, 'versionPushed')).toBeVisible();
    // The server's file already matched the newest version, so only the push adds a row.
    await expect(page.getByRole('table').getByRole('button')).toHaveCount(3);
    await expect(page.getByRole('table').getByRole('row').nth(1)).toContainText(t('pushed'));
    expect(readRemote(SSH.envPath)!.equals(original!)).toBe(true);
    await journey.shot(page, 'env-pushed');
  });
});
