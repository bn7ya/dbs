import type { Locator, Page } from '@playwright/test';
import { Api } from './support/api';
import { SSH, TARGET } from './support/config';
import { baseUrlOf, expect, test } from './support/fixtures';
import type { Journey } from './support/fixtures.types';

test.describe.configure({ mode: 'serial' });

const stepIs = async (form: Locator, name: string): Promise<void> => {
  await expect(form.getByRole('button', { name: new RegExp(`^${name}`), expanded: true })).toBeVisible();
};

type Pick = (page: Page, form: Locator, journey: Journey) => Promise<void>;

const fromTheSuggestions =
  (folder: string): Pick =>
  async (_page, form, { t }) => {
    await form.getByRole('button', { name: t('next'), exact: true }).click();
    await stepIs(form, t('stepDiscovery'));
    await form.getByRole('region', { name: t('projectFolders') }).getByRole('button', { name: folder }).click();
  };

const fromTheBrowser =
  (folder: string): Pick =>
  async (page, form, { t, say }) => {
    await form.getByRole('button', { name: say('browseFor', { field: t('folderOnServer') }) }).click();
    const browser = page.getByRole('dialog', { name: t('chooseFolderToSearch') });
    await browser.getByRole('navigation').getByRole('button', { name: '/', exact: true }).click();
    for (const part of folder.split('/').filter(Boolean)) {
      await browser.getByRole('button', { name: say('openEntry', { name: part }), exact: true }).click();
    }
    await expect(browser.getByText(t('djangoProjectHere'))).toBeVisible({ timeout: 60_000 });
    await browser.getByRole('button', { name: t('chooseThisFolder') }).click();
    await expect(browser).toBeHidden();
    await expect(form.getByRole('textbox', { name: t('folderOnServer') })).toHaveValue(folder);
    await form.getByRole('button', { name: t('next'), exact: true }).click();
  };

const addApplication = async (
  page: Page,
  journey: Journey,
  serverId: string,
  name: string,
  folder: string,
  python: string,
  pick: Pick,
): Promise<void> => {
  const { t } = journey;
  await page.goto(`/servers/${serverId}/applications/new`);
  const form = page.getByRole('main');
  const next = form.getByRole('button', { name: t('next'), exact: true });

  await pick(page, form, journey);
  await stepIs(form, t('stepDiscovery'));
  await expect(form.getByRole('radio', { name: `${t('onTheServer')} ${folder}` })).toBeChecked({ timeout: 120_000 });
  await next.click();

  await stepIs(form, t('stepReview'));
  await form.getByRole('textbox', { name: t('name'), exact: true }).fill(name);
  await form.getByRole('button', { name: t('showMoreSettings') }).click();
  await expect(form.getByRole('textbox', { name: t('projectFolder') })).toHaveValue(folder);
  await expect(form.getByRole('combobox', { name: t('pythonCommand') })).toHaveValue(python);
  await form.getByRole('button', { name: t('addApplicationSubmit'), exact: true }).click();
  await journey.confirmPassword(page, 'continue');

  await stepIs(form, t('stepCheck'));
  await expect(form.getByText(t('versionsWork'))).toBeVisible({ timeout: 120_000 });
  await next.click();
  await form.getByRole('button', { name: t('readPassphrase') }).click();
  await expect(form.getByText(t('passphraseSaved'))).toBeVisible({ timeout: 60_000 });
  await next.click();
  await form.getByRole('button', { name: t('takeTestBackup') }).click();
  await expect(form.getByText(t('testBackupWorked'))).toBeVisible({ timeout: 180_000 });
};

test.describe('two applications on one server', () => {
  test.skip(TARGET.projectDir === '', 'needs a second Django project with django-dbs on the SSH fixture');

  let api: Api;
  let prefix = '';
  let serverId = '';

  test.beforeAll(async ({}, testInfo) => {
    api = await Api.signIn(baseUrlOf(testInfo));
    prefix = `e2e pair ${testInfo.project.name} ${Date.now().toString(36)}`;
    serverId = (await api.createServer(prefix)).id;
  });

  test.afterAll(async () => {
    await api.deleteServersNamed(prefix);
  });

  test('each application is found, checked and backed up on its own', async ({ page, journey }) => {
    test.setTimeout(600_000);
    await journey.signIn(page);
    const first = `${prefix} first`;
    const second = `${prefix} second`;

    const suggested = fromTheSuggestions(SSH.projectDir);
    await addApplication(page, journey, serverId, first, SSH.projectDir, SSH.python, suggested);
    await journey.shot(page, 'two-applications-first');
    const browsed = fromTheBrowser(TARGET.projectDir);
    await addApplication(page, journey, serverId, second, TARGET.projectDir, TARGET.python, browsed);
    await journey.shot(page, 'two-applications-second');

    const applications = await api.applicationsOf(serverId);
    const a = await api.application(applications.find((found) => found.name === first)!.id);
    const b = await api.application(applications.find((found) => found.name === second)!.id);
    expect(a.project_dir).toBe(SSH.projectDir);
    expect(b.project_dir).toBe(TARGET.projectDir);
    expect(a.python_path).toBe(SSH.python);
    expect(b.python_path).toBe(TARGET.python);
    expect([a.last_check_status, b.last_check_status]).toEqual(['ok', 'ok']);

    const [backupsOfA, backupsOfB] = await Promise.all([api.backups(a.id), api.backups(b.id)]);
    expect(backupsOfA).toHaveLength(1);
    expect(backupsOfB).toHaveLength(1);
    expect(backupsOfA[0].id).not.toBe(backupsOfB[0].id);

    await page.goto(`/servers/${serverId}/applications`);
    const list = page.getByRole('main').getByRole('table');
    await expect(list.getByRole('link', { name: first, exact: true })).toBeVisible();
    await expect(list.getByRole('link', { name: second, exact: true })).toBeVisible();
    await journey.shot(page, 'two-applications-listed');

    await page.goto('/');
    const card = page.getByRole('region', { name: prefix, exact: true });
    await expect(card.getByRole('link', { name: first, exact: true })).toBeVisible();
    await expect(card.getByRole('link', { name: second, exact: true })).toBeVisible();
  });

  test('checking one application leaves the other as it was', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    const applications = await api.applicationsOf(serverId);
    const [one, two] = [`${prefix} first`, `${prefix} second`].map(
      (name) => applications.find((found) => found.name === name)!,
    );
    const before = await api.application(two.id);

    await page.goto(`/applications/${one.id}`);
    const check = page.getByRole('main').getByRole('button', { name: t('checkNow') });
    await check.click();
    await expect(check).toBeEnabled({ timeout: 120_000 });
    await expect(page.getByRole('main').getByText(t('ready')).first()).toBeVisible();

    expect(await api.application(two.id)).toEqual(before);
  });
});
