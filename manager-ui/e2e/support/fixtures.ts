import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test as base, type Cookie, type TestInfo } from '@playwright/test';
import { ADMIN, SCREENSHOT_DIR } from './config';
import { copyIn } from './copy';
import { freshCode } from './totp';
import type { Lang } from './copy.types';
import type { Journey } from './fixtures.types';

const langOf = (info: TestInfo): Lang => (info.project.name === 'rtl' ? 'ar' : 'en');

// One sign-in per worker: each one spends a two-factor step, and steps come every 30 seconds.
const sessions = new Map<string, Cookie[]>();

export const test = base.extend<{ journey: Journey }>({
  journey: async ({}, use, testInfo) => {
    const lang = langOf(testInfo);
    const t = copyIn(lang);
    const stamp = Date.now().toString(36);
    mkdirSync(SCREENSHOT_DIR, { recursive: true });

    await use({
      lang,
      dir: lang === 'ar' ? 'rtl' : 'ltr',
      t,
      named: (action, target, suffix) =>
        [t(action), target, suffix ? t(suffix) : null].filter((p) => p !== null).join(' '),
      unique: (what) => `e2e ${what} ${lang} ${stamp}`,
      signIn: async (page, user = ADMIN) => {
        const kept = sessions.get(user.username);
        if (kept) {
          await page.context().addCookies(kept);
          if ((await page.request.get('/api/auth/me/')).ok()) {
            await page.goto('/');
            await expect(page).not.toHaveURL(/\/sign-in/);
            return;
          }
          sessions.delete(user.username);
        }
        await page.goto('/sign-in');
        await page.getByRole('textbox', { name: t('username') }).fill(user.username);
        await page.getByLabel(t('password'), { exact: true }).fill(user.password);
        await page.getByRole('button', { name: t('signIn'), exact: true }).click();
        await expect(page).toHaveURL(/\/sign-in\/code/);
        await page.getByRole('textbox', { name: t('code') }).fill(await freshCode());
        await page.getByRole('button', { name: t('continue'), exact: true }).click();
        await expect(page).not.toHaveURL(/\/sign-in/);
        sessions.set(user.username, await page.context().cookies());
      },
      shot: async (page, name) => {
        await page.screenshot({
          path: join(SCREENSHOT_DIR, `${name}-${testInfo.project.name}.png`),
          fullPage: true,
        });
      },
      // The toast's text is also announced by a live region; the toast itself comes first.
      toast: (page, key) => page.getByText(t(key), { exact: true }).first(),
      shown: (scope, text) => scope.getByText(text, { exact: true }).filter({ visible: true }),
      signOut: async (page, user = ADMIN) => {
        await page.getByRole('banner').getByRole('button', { name: new RegExp(user.username) }).click();
        await page.getByRole('menuitem', { name: t('signOut') }).click();
        sessions.delete(user.username);
      },
      dismissToasts: async (page) => {
        for (const button of await page.getByRole('button', { name: t('dismiss') }).all()) {
          await button.click().catch(() => undefined);
        }
      },
    });
  },
});

export { expect };

export const plain = (text: string): string => text.replace(/[⁦-⁩]/g, '');
