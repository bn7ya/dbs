import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test as base, type TestInfo } from '@playwright/test';
import { ADMIN, SCREENSHOT_DIR } from './config';
import { copyIn } from './copy';
import type { Lang } from './copy.types';
import type { Journey } from './fixtures.types';

const langOf = (info: TestInfo): Lang => (info.project.name === 'rtl' ? 'ar' : 'en');

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
        await page.goto('/sign-in');
        await page.getByRole('textbox', { name: t('username') }).fill(user.username);
        await page.getByRole('textbox', { name: t('password'), exact: true }).fill(user.password);
        await page.getByRole('button', { name: t('signIn'), exact: true }).click();
        await expect(page).not.toHaveURL(/\/sign-in/);
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
