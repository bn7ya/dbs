import { statSync } from 'node:fs';
import { Api } from './support/api';
import { ADMIN, SSH } from './support/config';
import { expect, test } from './support/fixtures';
import { folderSnapshot } from './support/ssh-fs';

test.describe.configure({ mode: 'serial' });

test.describe('plans', () => {
  let api: Api;
  let serverId = '';
  let backupsUrl = '';
  let remoteFolder: ReturnType<typeof folderSnapshot>;
  const names = { dbs: '', archive: '', collect: '' };

  test.beforeAll(async ({}, testInfo) => {
    api = await Api.signIn(testInfo.project.use.baseURL ?? 'http://localhost:4200');
    remoteFolder = folderSnapshot(SSH.remoteBackupDir);
    const server = await api.createServer(`e2e plans ${testInfo.project.name} ${Date.now().toString(36)}`);
    serverId = server.id;
    backupsUrl = `/servers/${serverId}/backups`;
    const stamp = Date.now().toString(36);
    names.dbs = `e2e daily ${stamp}`;
    names.archive = `e2e media ${stamp}`;
    names.collect = `e2e collect ${stamp}`;
  });

  test.afterAll(async () => {
    await api.deleteServer(serverId);
    await api.dispose();
    remoteFolder.restore();
  });

  test('the plan form refuses an empty name and a keep count of zero', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(backupsUrl);
    await page.getByRole('button', { name: t('createDbsPlan') }).click();
    const dialog = page.getByRole('dialog');

    await dialog.getByRole('textbox', { name: t('name'), exact: true }).fill('');
    await dialog.getByRole('spinbutton', { name: t('keepHere') }).fill('0');
    await dialog.getByRole('button', { name: t('addPlanSubmit'), exact: true }).click();

    await expect(dialog.getByRole('textbox', { name: t('name'), exact: true })).toHaveAttribute('aria-invalid', 'true');
    await expect(dialog.getByRole('spinbutton', { name: t('keepHere') })).toHaveAttribute('aria-invalid', 'true');
    await expect(dialog).toBeVisible();
    await journey.shot(page, 'plan-form-validation');
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
  });

  test('a daily django-dbs plan that keeps two runs now and succeeds', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(backupsUrl);
    await page.getByRole('button', { name: t('createDbsPlan') }).click();
    const dialog = page.getByRole('dialog');

    await expect(dialog.getByRole('combobox', { name: t('schedule') })).toContainText(t('daily'));
    await dialog.getByRole('textbox', { name: t('name'), exact: true }).fill(names.dbs);
    await dialog.getByRole('spinbutton', { name: t('keepHere') }).fill('2');
    await journey.shot(page, 'plan-form');
    await dialog.getByRole('button', { name: t('addPlanSubmit'), exact: true }).click();

    await expect(journey.toast(page, 'planAdded')).toBeVisible();
    await expect(journey.shown(page, names.dbs)).toBeVisible();
    await expect(journey.shown(page, t('notRunYet'))).toBeVisible();
    await journey.dismissToasts(page);

    const run = page.getByRole('button', { name: journey.named('run', names.dbs, 'now') });
    await run.click();
    await expect(run).toHaveAttribute('aria-disabled', 'true');

    await expect(journey.toast(page, 'backupFinished')).toBeVisible({ timeout: 180_000 });
    await expect(journey.shown(page, t('succeeded'))).toBeVisible();
    await expect(page.getByRole('link', { name: new RegExp(`^${t('download')} .+\\.dbs$`) })).toBeVisible();
    await journey.shot(page, 'plan-ran');
  });

  test('a folders plan archives the media folder and the archive downloads', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(backupsUrl);
    await page.getByRole('button', { name: t('addPlan'), exact: true }).click();
    const dialog = page.getByRole('dialog');

    const kind = dialog.getByRole('radio', { name: t('kindFolders') });
    await kind.click();
    await expect(kind).toBeChecked();
    const folders = dialog.getByRole('textbox', { name: t('folders') });
    await folders.fill(SSH.mediaDir);
    await folders.press('Enter');
    await expect(dialog.getByRole('row').filter({ hasText: SSH.mediaDir })).toBeVisible();
    await dialog.getByRole('textbox', { name: t('name'), exact: true }).fill(names.archive);
    // What a folders plan reads is chosen behind the reader's own password.
    await dialog.getByLabel(t('yourPassword'), { exact: true }).fill(ADMIN.password);
    await dialog.getByRole('button', { name: t('addPlanSubmit'), exact: true }).click();

    await expect(journey.toast(page, 'planAdded')).toBeVisible();
    await journey.dismissToasts(page);
    await page.getByRole('button', { name: journey.named('run', names.archive, 'now') }).click();

    await expect(journey.toast(page, 'backupFinished')).toBeVisible({ timeout: 180_000 });
    const link = page.getByRole('link', { name: new RegExp(`^${t('download')} .+\\.tar\\.gz$`) });
    await expect(link).toBeVisible();
    const [download] = await Promise.all([page.waitForEvent('download'), link.click()]);
    expect(download.suggestedFilename()).toMatch(/\.tar\.gz$/);
    expect(statSync(await download.path()).size).toBeGreaterThan(0);
    await journey.shot(page, 'plan-archive');
  });

  test('an existing-files plan collects the .sql.gz files once, then nothing new', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(backupsUrl);
    await page.getByRole('button', { name: t('addPlan'), exact: true }).click();
    const dialog = page.getByRole('dialog');

    const kind = dialog.getByRole('radio', { name: t('kindExisting') });
    await kind.click();
    await expect(kind).toBeChecked();
    await dialog.getByRole('textbox', { name: t('folder'), exact: true }).fill(SSH.existingDir);
    await dialog.getByRole('textbox', { name: t('pattern') }).fill('*.sql.gz');
    await dialog.getByRole('textbox', { name: t('name'), exact: true }).fill(names.collect);
    await dialog.getByLabel(t('yourPassword'), { exact: true }).fill(ADMIN.password);
    await journey.shot(page, 'plan-form-collect');
    await dialog.getByRole('button', { name: t('addPlanSubmit'), exact: true }).click();

    await expect(journey.toast(page, 'planAdded')).toBeVisible();
    await expect(journey.shown(page, `${SSH.existingDir}/*.sql.gz`)).toBeVisible();
    await journey.dismissToasts(page);
    const run = page.getByRole('button', { name: journey.named('run', names.collect, 'now') });
    await run.click();

    await expect(journey.toast(page, 'collected')).toBeVisible({ timeout: 180_000 });
    for (const file of SSH.existingFiles) {
      await expect(page.getByRole('link', { name: journey.named('download', file) })).toBeVisible();
    }
    await journey.shot(page, 'plan-collected');
    await journey.dismissToasts(page);

    await run.click();

    await expect(journey.toast(page, 'nothingNew')).toBeVisible({ timeout: 180_000 });
    await expect(page.getByRole('link', { name: new RegExp(`^${t('download')} .+\\.sql\\.gz$`) })).toHaveCount(
      SSH.existingFiles.length,
    );
  });

  test('deleting a plan keeps its backups listed', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(backupsUrl);
    const archives = page.getByRole('link', { name: new RegExp(`^${t('download')} .+\\.tar\\.gz$`) });
    await expect(archives).toHaveCount(1);

    await page.getByRole('button', { name: journey.named('delete', names.archive) }).click();
    const confirm = page.getByRole('alertdialog');
    await expect(confirm.getByRole('heading', { level: 2 })).toContainText(names.archive);
    await confirm.getByRole('button', { name: t('delete'), exact: true }).click();

    await expect(journey.toast(page, 'planDeleted')).toBeVisible();
    await expect(page.getByRole('button', { name: journey.named('run', names.archive, 'now') })).toHaveCount(0);
    await expect(archives).toHaveCount(1);
  });
});
