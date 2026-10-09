import { expect, test } from './support/fixtures';

test('repeated wrong sign-ins lock the attempts out with a plain message', async ({ page, journey }) => {
  const { t } = journey;
  const username = `e2e-lock-${journey.dir}-${Date.now().toString(36)}`;
  await page.goto('/sign-in');

  const attempt = async () => {
    await page.getByRole('textbox', { name: t('username') }).fill(username);
    await page.getByRole('textbox', { name: t('password'), exact: true }).fill('wrong-password');
    const response = page.waitForResponse((r) => r.url().endsWith('/api/auth/login/'));
    await page.getByRole('button', { name: t('signIn'), exact: true }).click();
    return (await response).status();
  };

  let status = 0;
  let attempts = 0;
  while (status !== 429 && attempts < 10) {
    status = await attempt();
    attempts += 1;
    await expect(page.getByRole('alert')).toBeVisible();
    if (status !== 429) await expect(page.getByRole('alert')).toHaveText(t('wrongCredentials'));
  }

  expect(status).toBe(429);
  expect(attempts).toBeGreaterThan(1);
  await expect(page.getByRole('alert')).toHaveText(t('tooManyAttempts'));
  await expect(page).toHaveURL(/\/sign-in/);
  await journey.shot(page, 'sign-in-locked');
});
