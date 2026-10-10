import type { Locator, Page } from '@playwright/test';
import { Api } from './support/api';
import { SSH, TARGET } from './support/config';
import { expect, test } from './support/fixtures';
import type { Journey } from './support/fixtures.types';

test.describe.configure({ mode: 'serial' });

const stepIs = async (page: Page, name: string): Promise<void> => {
  await expect(page.getByRole('button', { name: new RegExp(name), expanded: true })).toBeVisible();
};

const fromTheList =
  (folder: string) =>
  async (_page: Page, form: Locator): Promise<void> => {
    await form.getByRole('radio', { name: folder }).click();
  };

const fromTheBrowser =
  (folder: string) =>
  async (page: Page, form: Locator, { t }: Journey): Promise<void> => {
    await form.getByRole('button', { name: t('browseServer'), exact: true }).click();
    const browser = page.getByRole('dialog', { name: t('chooseProjectFolder') });
    await browser.getByRole('button', { name: folder }).click();
    await expect(browser.getByText(t('djangoProjectHere'))).toBeVisible({ timeout: 60_000 });
    await browser.getByRole('button', { name: t('chooseThisFolder') }).click();
    await expect(browser).toBeHidden();
  };

const addServer = async (
  page: Page,
  journey: Journey,
  name: string,
  folder: string,
  pick: (page: Page, form: Locator, journey: Journey) => Promise<void>,
): Promise<void> => {
  const { t } = journey;
  await page.goto('/servers/new');
  const form = page.getByRole('main');
  const next = form.getByRole('button', { name: t('next'), exact: true });

  await next.click();
  await form.getByRole('textbox', { name: t('name'), exact: true }).fill(name);
  await form.getByRole('textbox', { name: t('host'), exact: true }).fill(SSH.host);
  await form.getByRole('spinbutton', { name: t('port') }).fill(String(SSH.port));
  await form.getByRole('textbox', { name: t('username') }).fill(SSH.username);
  await form.getByRole('button', { name: t('getHostKey') }).click();
  await expect(form.getByRole('definition').filter({ hasText: /^SHA256:/ })).toHaveText(SSH.fingerprint);
  await form.getByRole('checkbox', { name: t('fingerprintsMatch') }).click();
  await next.click();
  await form.getByRole('radio', { name: t('password'), exact: true }).click();
  await form.getByLabel(t('serverPassword'), { exact: true }).fill(SSH.password);
  await form.getByRole('button', { name: t('addServerSubmit'), exact: true }).click();

  await stepIs(page, t('stepProject'));
  await expect(form.getByRole('button', { name: t('findProject') })).toBeEnabled({ timeout: 60_000 });
  await pick(page, form, journey);
  await expect(form.getByRole('textbox', { name: t('projectFolder') })).toHaveValue(folder);
  await expect(form.getByText(t('projectReady'))).toBeVisible({ timeout: 60_000 });
  await expect(form.getByRole('combobox', { name: t('pythonCommand') })).toHaveValue(new RegExp(`^${folder}/`));
  await next.click();

  await stepIs(page, t('stepCheck'));
  await expect(form.getByText(t('versionsWork'))).toBeVisible({ timeout: 120_000 });
  await next.click();
  await form.getByRole('button', { name: t('readPassphrase') }).click();
  await expect(form.getByText(t('passphraseSaved'))).toBeVisible({ timeout: 60_000 });
  await next.click();
  await form.getByRole('button', { name: t('takeTestBackup') }).click();
  await expect(form.getByText(t('testBackupWorked'))).toBeVisible({ timeout: 180_000 });
};

test.describe('two projects on one server', () => {
  // The fixture serves one Django project unless E2E_SSH_TARGET_PROJECT_DIR names a second one.
  test.skip(TARGET.projectDir === '', 'needs a second Django project with django-dbs on the SSH fixture');

  let api: Api;
  let prefix = '';

  test.beforeAll(async ({}, testInfo) => {
    api = await Api.signIn(testInfo.project.use.baseURL ?? 'http://localhost:4200');
    prefix = `e2e pair ${testInfo.project.name} ${Date.now().toString(36)}`;
  });

  test.afterAll(async () => {
    for (const server of await api.findServers(prefix)) await api.deleteServer(server.id);
    await api.dispose();
  });

  test('each connection finds, checks and backs up its own project', async ({ page, journey }) => {
    test.setTimeout(600_000);
    await journey.signIn(page);
    const first = `${prefix} first`;
    const second = `${prefix} second`;

    await addServer(page, journey, first, SSH.projectDir, fromTheList(SSH.projectDir));
    await journey.shot(page, 'two-projects-first');
    await addServer(page, journey, second, TARGET.projectDir, fromTheBrowser(TARGET.projectDir));
    await journey.shot(page, 'two-projects-second');

    const [one, two] = await Promise.all([first, second].map(async (name) => (await api.findServers(name))[0]));
    const [a, b] = await Promise.all([api.server(one.id), api.server(two.id)]);
    expect(a.project_dir).toBe(SSH.projectDir);
    expect(b.project_dir).toBe(TARGET.projectDir);
    expect(a.python_path).not.toBe(b.python_path);
    expect(a.python_path.startsWith(SSH.projectDir)).toBe(true);
    expect(b.python_path.startsWith(TARGET.projectDir)).toBe(true);
    expect([a.last_check_status, b.last_check_status]).toEqual(['ok', 'ok']);

    const [backupsOfA, backupsOfB] = await Promise.all([api.backups(a.id), api.backups(b.id)]);
    expect(backupsOfA).toHaveLength(1);
    expect(backupsOfB).toHaveLength(1);
    expect(backupsOfA[0].id).not.toBe(backupsOfB[0].id);

    await page.goto(`/servers?search=${encodeURIComponent(prefix)}`);
    const list = page.getByRole('main');
    await expect(list.getByRole('link', { name: first })).toBeVisible();
    await expect(list.getByRole('link', { name: second })).toBeVisible();
  });

  test('re-checking one server leaves the other as it was', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    const [one, two] = await Promise.all([`${prefix} first`, `${prefix} second`].map(async (name) => (await api.findServers(name))[0]));
    const before = await api.server(two.id);

    await page.goto(`/servers/${one.id}`);
    const check = page.getByRole('button', { name: t('checkNow') });
    await check.click();
    await expect(check).toBeEnabled({ timeout: 120_000 });
    await expect(page.getByRole('main').getByText(t('ready')).first()).toBeVisible();

    const after = await api.server(two.id);
    expect(after).toEqual(before);
  });
});
