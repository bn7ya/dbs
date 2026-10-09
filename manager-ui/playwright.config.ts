import { existsSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { defineConfig, devices } from '@playwright/test';

const chromium =
  process.env['E2E_CHROMIUM'] ??
  (existsSync('/opt/pw-browsers/chromium') ? '/opt/pw-browsers/chromium' : undefined);

const port = process.env['E2E_PORT'] ?? '8799';
const baseURL = process.env['E2E_BASE_URL'] ?? `http://127.0.0.1:${port}`;

// Workers inherit the runner's environment, so every process reads the one data dir made here.
const dataDir = process.env['E2E_DATA_DIR'] ?? mkdtempSync(join(tmpdir(), 'dbs-manager-e2e-'));
process.env['E2E_DATA_DIR'] = dataDir;

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
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    ...(chromium ? { launchOptions: { executablePath: chromium } } : {}),
  },

  webServer: process.env['E2E_BASE_URL']
    ? undefined
    : {
        command: `django_dbs run --no-browser --port ${port} --data-dir ${dataDir}`,
        url: `${baseURL}/api/setup/`,
        reuseExistingServer: false,
        stdout: 'pipe',
        timeout: 120_000,
      },

  projects: [
    { name: 'setup', testMatch: /00-setup\.spec\.ts/, use: { ...devices['Desktop Chrome'], locale: 'en-US' } },
    {
      name: 'ltr',
      testIgnore: /00-setup\.spec\.ts/,
      dependencies: ['setup'],
      use: { ...devices['Desktop Chrome'], locale: 'en-US' },
    },
    {
      name: 'rtl',
      testIgnore: /00-setup\.spec\.ts/,
      dependencies: ['setup'],
      use: { ...devices['Desktop Chrome'], locale: 'ar' },
    },
  ],
});
