import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test as base, type TestInfo } from '@playwright/test';
import { Api } from './api';
import { ADMIN, SCREENSHOT_DIR } from './config';
import { copyIn } from './copy';
import type { CopyKey, Lang } from './copy.types';
import type { Journey } from './fixtures.types';

const langOf = (info: TestInfo): Lang => (info.project.name === 'rtl' ? 'ar' : 'en');

export const baseUrlOf = (info: TestInfo): string => info.project.use.baseURL ?? 'http://127.0.0.1:8799';

export const test = base.extend<{ journey: Journey }>({
  journey: async ({}, use, testInfo) => {
    const lang = langOf(testInfo);
    const t = copyIn(lang);
    const say = (key: CopyKey, values: Record<string, string>): string =>
      t(key).replace(/\{(\w+)\}/g, (_, name: string) => values[name] ?? '');
    mkdirSync(SCREENSHOT_DIR, { recursive: true });

    await use({
      lang,
      dir: lang === 'ar' ? 'rtl' : 'ltr',
      t,
      say,
      matching: (key, name) => new RegExp(`^${say(key, { name })}$`),
      // Pages share the worker's API session: a sign-in spends a two-factor step, and one comes every 30 seconds.
      signIn: async (page, user = ADMIN) => {
        const api = await Api.signIn(baseUrlOf(testInfo), user);
        await page.context().addCookies(await api.cookies());
        await page.goto('/');
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
      signOut: async (page, user = ADMIN) => {
        await page.getByRole('banner').getByRole('button', { name: new RegExp(user.username) }).click();
        await page.getByRole('menuitem', { name: t('signOut') }).click();
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
