import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test, type APIRequestContext } from '@playwright/test';
import { ADMIN, DATA_DIR, SETUP_TOKEN } from './support/config';
import { copyIn } from './support/copy';

const t = copyIn('en');

const setupNeeded = async (request: APIRequestContext): Promise<boolean> =>
  ((await (await request.get('/api/setup/')).json()) as { needed: boolean }).needed;

const setupToken = (): string => SETUP_TOKEN ?? readFileSync(join(DATA_DIR, 'setup.token'), 'utf8').trim();

test('the first visit creates the account from the setup link the server printed', async ({ page, request }) => {
  test.skip(!(await setupNeeded(request)), 'The manager already has an account.');

  await page.goto('/servers');
  await expect(page).toHaveURL(/\/setup$/);
  await expect(page.getByRole('textbox', { name: t('setupKey') })).toBeVisible();

  await page.goto(`/setup?token=${encodeURIComponent(setupToken())}`);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(t('setupTitle'));
  await expect(page.getByRole('textbox', { name: t('setupKey') })).toHaveCount(0);

  await page.getByRole('textbox', { name: t('username') }).fill(ADMIN.username);
  await page.getByLabel(t('password'), { exact: true }).fill(ADMIN.password);
  await page.getByLabel(t('confirmPassword'), { exact: true }).fill(`${ADMIN.password}-typo`);
  await page.getByRole('button', { name: t('createAccount') }).click();
  await expect(page.getByText(t('passwordsDiffer'))).toBeVisible();

  await page.getByLabel(t('confirmPassword'), { exact: true }).fill(ADMIN.password);
  await page.getByRole('button', { name: t('createAccount') }).click();

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('banner')).toContainText(ADMIN.username);
  expect(await setupNeeded(page.request)).toBe(false);

  await page.goto('/setup');
  await expect(page).toHaveURL(/\/$/);
});
