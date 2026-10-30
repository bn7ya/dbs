import { ADMIN } from './support/config';
import { expect, test } from './support/fixtures';
import { freshCode } from './support/totp';

test.describe('a developer signs in to the manager, finds their way around and signs out', () => {
  test('a visitor who is not signed in is sent to sign in, and the API refuses on its own', async ({
    page,
    request,
    journey,
  }) => {
    await page.goto('/servers');

    await expect(page).toHaveURL(/\/sign-in\?next=%2Fservers/);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(journey.t('signInTitle'));
    await expect(page.locator('html')).toHaveAttribute('dir', journey.dir);

    expect((await request.get('/api/servers/')).status()).toBe(403);
    expect((await request.get('/api/activity/')).status()).toBe(403);
    await journey.shot(page, 'sign-in');
  });

  test('the sign-in form names each missing field and is reached by keyboard first', async ({ page, journey }) => {
    const { t } = journey;
    await page.goto('/sign-in');
    const username = page.getByRole('textbox', { name: t('username') });
    await expect(username).toBeVisible();

    // The skip link belongs to the signed-in shell, so the username is the first stop here.
    await page.keyboard.press('Tab');
    await expect(username).toBeFocused();

    await page.getByRole('button', { name: t('signIn'), exact: true }).click();

    await expect(page.getByText(t('usernameRequired'))).toBeVisible();
    await expect(page.getByText(t('passwordRequired'))).toBeVisible();
  });

  test('a wrong password says so, and the right one with a code opens the dashboard', async ({ page, journey }) => {
    const { t } = journey;
    await page.goto('/sign-in');
    await page.getByRole('textbox', { name: t('username') }).fill(ADMIN.username);
    await page.getByLabel(t('password'), { exact: true }).fill('not-the-password');
    await page.getByRole('button', { name: t('signIn'), exact: true }).click();

    await expect(page.getByRole('alert')).toHaveText(t('wrongCredentials'));
    await expect(page).toHaveURL(/\/sign-in/);
    await journey.shot(page, 'sign-in-wrong-password');

    await page.getByLabel(t('password'), { exact: true }).fill(ADMIN.password);
    await page.getByRole('button', { name: t('signIn'), exact: true }).click();

    await expect(page.getByRole('heading', { level: 1 })).toHaveText(t('twoFactorTitle'));
    await page.getByRole('textbox', { name: t('code') }).fill(await freshCode());
    await page.getByRole('button', { name: t('continue'), exact: true }).click();

    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(t('dashboardTitle'));
    await expect(page.getByRole('banner')).toContainText(ADMIN.username);
    const nav = page.getByRole('navigation', { name: t('navMain') });
    const sections = ['navDashboard', 'navServers', 'navApplications', 'navBackups', 'navConsole', 'navActivity'] as const;
    for (const section of sections) {
      await expect(nav.getByRole('link', { name: t(section) })).toBeVisible();
    }
    await journey.shot(page, 'dashboard');
  });

  test('someone guessing passwords is locked out with a plain message', async ({ page, journey }) => {
    const { t } = journey;
    const username = `e2e-lock-${journey.dir}-${Date.now().toString(36)}`;
    await page.goto('/sign-in');

    const attempt = async (): Promise<number> => {
      await page.getByRole('textbox', { name: t('username') }).fill(username);
      await page.getByLabel(t('password'), { exact: true }).fill('wrong-password');
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

  test('the signed-in shell is reachable by keyboard, from the skip link to every section', async ({
    page,
    journey,
  }) => {
    const { t } = journey;
    await journey.signIn(page);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    await page.keyboard.press('Tab');
    await expect(page.getByRole('link', { name: t('skipToContent') })).toBeFocused();

    const nav = page.getByRole('navigation', { name: t('navMain') });
    const dashboard = nav.getByRole('link', { name: t('navDashboard') });
    for (let stop = 0; stop < 8 && !(await dashboard.evaluate((el) => el === document.activeElement)); stop += 1) {
      await page.keyboard.press('Tab');
    }
    await expect(dashboard).toBeFocused();
    for (const section of ['navServers', 'navApplications', 'navBackups', 'navConsole', 'navActivity'] as const) {
      await page.keyboard.press('Tab');
      await expect(nav.getByRole('link', { name: t(section) })).toBeFocused();
    }
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/\/activity$/);
  });

  test('the other language flips the direction and the words, and switching back restores them', async ({
    page,
    journey,
  }) => {
    await journey.signIn(page);
    await page.goto('/servers');
    const other = journey.lang === 'ar' ? 'English' : 'العربية';
    const otherDir = journey.lang === 'ar' ? 'ltr' : 'rtl';
    const otherLang = journey.lang === 'ar' ? 'en' : 'ar';
    const otherTitle = journey.lang === 'ar' ? 'Servers' : 'الخوادم';

    await page.getByRole('radiogroup', { name: journey.t('language') }).getByRole('radio', { name: other }).click();

    await expect(page.locator('html')).toHaveAttribute('dir', otherDir);
    await expect(page.locator('html')).toHaveAttribute('lang', otherLang);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(otherTitle);
    await journey.shot(page, 'servers-other-language');

    await page
      .getByRole('radiogroup', { name: journey.lang === 'ar' ? 'Language' : 'اللغة' })
      .getByRole('radio', { name: journey.lang === 'ar' ? 'العربية' : 'English' })
      .click();

    await expect(page.locator('html')).toHaveAttribute('dir', journey.dir);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(journey.t('serversTitle'));
  });

  test('the account menu opens About, with the version and the export command', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);

    await page.getByRole('banner').getByRole('button', { name: new RegExp(ADMIN.username) }).click();
    await page.getByRole('menuitem', { name: t('aboutDbs') }).click();

    await expect(page).toHaveURL(/\/about$/);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(t('aboutDbs'));
    await expect(page.getByRole('term').filter({ hasText: t('version') })).toBeVisible();
    await expect(page.getByRole('main').getByText('django_dbs export manager.dbs', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: t('copyExportCommand'), exact: true })).toBeVisible();
    await journey.shot(page, 'about');
  });

  test('signing out ends the session in the browser and on the server', async ({ page, journey }) => {
    await journey.signIn(page);

    await journey.signOut(page);

    await expect(page).toHaveURL(/\/sign-in/);
    await page.goto('/activity');
    await expect(page).toHaveURL(/\/sign-in\?next=%2Factivity/);
    expect((await page.request.get('/api/auth/me/')).status()).toBe(403);
  });
});
