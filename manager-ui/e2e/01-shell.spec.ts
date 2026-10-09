import { ADMIN } from './support/config';
import { expect, test } from './support/fixtures';

test.describe('the shell', () => {
  test('a signed-out visitor is sent to sign in, and the API refuses on its own', async ({
    page,
    request,
    journey,
  }) => {
    await page.goto('/servers');

    await expect(page).toHaveURL(/\/sign-in\?next=%2Fservers/);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(journey.t('signInTitle'));
    await expect(page.locator('html')).toHaveAttribute('dir', journey.dir);

    // Rule 21: the backend is the boundary, with or without the guard.
    expect((await request.get('/api/servers/')).status()).toBe(403);
    expect((await request.get('/api/activity/')).status()).toBe(403);
    await journey.shot(page, 'sign-in');
  });

  test('a wrong password says so, and the right one opens the dashboard', async ({ page, journey }) => {
    await page.goto('/sign-in');
    await page.getByRole('textbox', { name: journey.t('username') }).fill(ADMIN.username);
    await page.getByLabel(journey.t('password'), { exact: true }).fill('not-the-password');
    await page.getByRole('button', { name: journey.t('signIn'), exact: true }).click();

    await expect(page.getByRole('alert')).toHaveText(journey.t('wrongCredentials'));
    await expect(page).toHaveURL(/\/sign-in/);
    await journey.shot(page, 'sign-in-wrong-password');

    await page.getByLabel(journey.t('password'), { exact: true }).fill(ADMIN.password);
    await page.getByRole('button', { name: journey.t('signIn'), exact: true }).click();

    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(journey.t('dashboardTitle'));
    await expect(page.getByRole('banner')).toContainText(ADMIN.username);
    const nav = page.getByRole('navigation', { name: /.+/ }).first();
    await expect(nav.getByRole('link', { name: journey.t('navDashboard') })).toBeVisible();
    await expect(nav.getByRole('link', { name: journey.t('navServers') })).toBeVisible();
    await expect(nav.getByRole('link', { name: journey.t('navActivity') })).toBeVisible();
    await journey.shot(page, 'dashboard');
  });

  test('the account menu opens About, with the version and the export command', async ({ page, journey }) => {
    await journey.signIn(page);

    await page.getByRole('banner').getByRole('button', { name: new RegExp(ADMIN.username) }).click();
    await page.getByRole('menuitem', { name: journey.t('aboutDbs') }).click();

    await expect(page).toHaveURL(/\/about$/);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(journey.t('aboutDbs'));
    await expect(page.getByRole('term').filter({ hasText: journey.t('version') })).toBeVisible();
    await expect(page.getByRole('main').getByText('django_dbs export manager.dbs', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: journey.t('copyExportCommand'), exact: true })).toBeVisible();
    await journey.shot(page, 'about');
  });

  test('the language switch flips the direction and the words, and back', async ({ page, journey }) => {
    await journey.signIn(page);
    await page.goto('/servers');
    const other = journey.lang === 'ar' ? 'English' : 'العربية';
    const otherDir = journey.lang === 'ar' ? 'ltr' : 'rtl';
    const otherTitle = journey.lang === 'ar' ? 'Servers' : 'الخوادم';

    await page.getByRole('radiogroup', { name: journey.t('language') }).getByRole('radio', { name: other }).click();

    await expect(page.locator('html')).toHaveAttribute('dir', otherDir);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(otherTitle);
    await journey.shot(page, 'servers-other-language');

    const languageLabel = journey.lang === 'ar' ? 'Language' : 'اللغة';
    await page
      .getByRole('radiogroup', { name: languageLabel })
      .getByRole('radio', { name: journey.lang === 'ar' ? 'العربية' : 'English' })
      .click();

    await expect(page.locator('html')).toHaveAttribute('dir', journey.dir);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(journey.t('serversTitle'));
  });

  test('sign out ends the session on both sides', async ({ page, journey }) => {
    await journey.signIn(page);

    await journey.signOut(page);

    await expect(page).toHaveURL(/\/sign-in/);
    await page.goto('/activity');
    await expect(page).toHaveURL(/\/sign-in\?next=%2Factivity/);
    expect((await page.request.get('/api/auth/me/')).status()).toBe(403);
  });

  test('the signed-in shell is reachable by keyboard', async ({ page, journey }) => {
    await journey.signIn(page);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    await page.keyboard.press('Tab');
    await expect(page.getByRole('link', { name: journey.t('skipToContent') })).toBeFocused();

    // The main navigation is a few stops in; every stop must be a named control.
    const dashboard = page.getByRole('link', { name: journey.t('navDashboard') });
    for (let stop = 0; stop < 8 && !(await dashboard.evaluate((el) => el === document.activeElement)); stop += 1) {
      await page.keyboard.press('Tab');
    }
    await expect(dashboard).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(page.getByRole('link', { name: journey.t('navServers') })).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(page.getByRole('link', { name: journey.t('navActivity') })).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/\/activity$/);
  });
});
