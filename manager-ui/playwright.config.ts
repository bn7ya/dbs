import { existsSync } from 'node:fs';
import { defineConfig, devices } from '@playwright/test';

const chromium =
  process.env['E2E_CHROMIUM'] ??
  (existsSync('/opt/pw-browsers/chromium') ? '/opt/pw-browsers/chromium' : undefined);

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env['CI'],
  retries: process.env['CI'] ? 2 : 0,
  reporter: process.env['CI'] ? 'github' : 'list',

  // A journey waits on real SSH work — a backup, a verification — that takes
  // tens of seconds each; the budget is per journey, not per click.
  timeout: 300_000,
  expect: { timeout: 15_000 },

  use: {
    baseURL: process.env['E2E_BASE_URL'] ?? 'http://localhost:4200',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    ...(chromium ? { launchOptions: { executablePath: chromium } } : {}),
  },

  projects: [
    { name: 'ltr', use: { ...devices['Desktop Chrome'], locale: 'en-US' } },
    { name: 'rtl', use: { ...devices['Desktop Chrome'], locale: 'ar' } },
  ],
});
