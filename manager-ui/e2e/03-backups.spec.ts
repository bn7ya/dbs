import { statSync } from 'node:fs';
import { Api } from './support/api';
import { SSH } from './support/config';
import { expect, test } from './support/fixtures';
import { folderSnapshot, remoteExists, remoteReachable, scratchFile } from './support/ssh-fs';

test.describe.configure({ mode: 'serial' });

test.describe('backups', () => {
  let api: Api;
  let serverId = '';
  let backupsUrl = '';
  let remoteFolder: ReturnType<typeof folderSnapshot>;
  let backupName = '';
  let uploadName = '';

  test.beforeAll(async ({}, testInfo) => {
    api = await Api.signIn(testInfo.project.use.baseURL ?? 'http://localhost:4200');
    remoteFolder = folderSnapshot(SSH.remoteBackupDir);
    const server = await api.createServer(`e2e backups ${testInfo.project.name} ${Date.now().toString(36)}`);
    serverId = server.id;
    backupsUrl = `/servers/${serverId}/backups`;
    uploadName = `e2e-upload-${testInfo.project.name}-${Date.now().toString(36)}.dbs`;
  });

  test.afterAll(async () => {
    await api.deleteServer(serverId);
    await api.dispose();
    remoteFolder.restore();
  });

  test('a new server has no plans and no backups', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(backupsUrl);

    await expect(page.getByRole('heading', { name: t('noPlansYet') })).toBeVisible();
    await expect(page.getByRole('heading', { name: t('noBackupsYet') })).toBeVisible();
    await expect(page.getByRole('button', { name: t('backUpNow') })).toBeVisible();
    await journey.shot(page, 'backups-empty');
  });

  test('Back up now runs on the server and lists the file', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(backupsUrl);

    const backUp = page.getByRole('button', { name: t('backUpNow') });
    await backUp.click();

    await expect(page.getByRole('status').filter({ hasText: t('backupRunning') })).toBeVisible();
    await expect(backUp).toHaveAttribute('aria-disabled', 'true');
    await journey.shot(page, 'backups-running');

    await expect(journey.toast(page, 'backupFinished')).toBeVisible({ timeout: 180_000 });
    await expect(backUp).not.toHaveAttribute('aria-disabled', 'true');
    const download = page.getByRole('link', { name: new RegExp(`^${t('download')} .+\\.dbs$`) }).first();
    await expect(download).toBeVisible();
    backupName = (await download.getAttribute('aria-label'))!.replace(`${t('download')} `, '');
    expect(backupName).toMatch(/\.dbs$/);
    await expect(journey.shown(page, t('structureChecked')).first()).toBeVisible();
    if (remoteReachable) {
      expect(remoteExists(`${SSH.remoteBackupDir}/${backupName}`)).toBe(true);
    }
    await journey.shot(page, 'backups-taken');
  });

  test('the file downloads under its own name', async ({ page, journey }) => {
    await journey.signIn(page);
    await page.goto(backupsUrl);

    const link = page.getByRole('link', { name: journey.named('download', backupName) });
    const [download] = await Promise.all([page.waitForEvent('download'), link.click()]);

    expect(download.suggestedFilename()).toBe(backupName);
    expect(statSync(await download.path()).size).toBeGreaterThan(0);
  });

  test('Verify runs a full check and the row says Verified', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(backupsUrl);

    const verify = page.getByRole('button', { name: journey.named('verify', backupName) });
    await verify.click();
    await expect(verify).toHaveAttribute('aria-disabled', 'true');

    await expect(journey.toast(page, 'checkPassed')).toBeVisible({ timeout: 180_000 });
    await expect(journey.shown(page, t('verified')).first()).toBeVisible();
    await journey.shot(page, 'backups-verified');
  });

  test('Delete asks first, then Undo brings the file back', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(backupsUrl);
    const link = page.getByRole('link', { name: journey.named('download', backupName) });
    await expect(link).toBeVisible();

    await page.getByRole('button', { name: journey.named('delete', backupName) }).click();
    const confirm = page.getByRole('alertdialog');
    await expect(confirm.getByRole('heading', { level: 2 })).toContainText(backupName);
    await confirm.getByRole('button', { name: t('delete'), exact: true }).click();

    await expect(journey.toast(page, 'backupDeleted')).toBeVisible();
    await expect(link).toBeHidden();
    await journey.shot(page, 'backups-deleted');

    await page.getByRole('button', { name: t('undo') }).click();

    await expect(journey.toast(page, 'deletionUndone')).toBeVisible();
    await expect(link).toBeVisible();
  });

  test('a file uploaded from disk is listed as uploaded', async ({ page, journey }, testInfo) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(backupsUrl);
    const file = scratchFile(testInfo.outputDir, uploadName, 'not a backup, just bytes\n');

    const [chooser] = await Promise.all([
      page.waitForEvent('filechooser'),
      page.getByRole('button', { name: t('uploadBackup') }).click(),
    ]);
    await chooser.setFiles(file);

    await expect(journey.toast(page, 'backupUploaded')).toBeVisible();
    await expect(journey.shown(page, t('uploaded'))).toBeVisible();
    await expect(page.getByRole('link', { name: journey.named('download', uploadName) })).toBeVisible();
    await journey.shot(page, 'backups-uploaded');
  });

  test('an uploaded file is checked for being intact, never called a verified backup', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(backupsUrl);
    const row = page.getByRole('row').filter({ hasText: uploadName }).filter({ visible: true });
    await expect(journey.shown(row, t('sealedStored'))).toBeVisible();

    await page.getByRole('button', { name: journey.named('verify', uploadName) }).click();

    await expect(journey.toast(page, 'checkPassed')).toBeVisible({ timeout: 180_000 });
    await expect(journey.shown(row, t('sealedIntact'))).toBeVisible();
    await expect(journey.shown(row, t('verified'))).toHaveCount(0);
    await journey.shot(page, 'backups-upload-intact');
  });
});
