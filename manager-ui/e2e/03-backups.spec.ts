import { statSync } from 'node:fs';
import { Api } from './support/api';
import { ADMIN, SSH } from './support/config';
import { baseUrlOf, expect, test } from './support/fixtures';
import { folderSnapshot, remoteExists, remoteReachable, scratchFile } from './support/ssh-fs';

test.describe.configure({ mode: 'serial' });

test.describe('backups', () => {
  let api: Api;
  let name = '';
  let backupsUrl = '';
  let remoteFolder: ReturnType<typeof folderSnapshot>;
  let backupName = '';
  let uploadName = '';

  test.beforeAll(async ({}, testInfo) => {
    api = await Api.signIn(baseUrlOf(testInfo));
    remoteFolder = folderSnapshot(SSH.remoteBackupDir);
    name = `e2e backups ${testInfo.project.name} ${Date.now().toString(36)}`;
    const { application } = await api.createServerWithApplication(name);
    await api.capturePassphrase(application.id);
    backupsUrl = `/applications/${application.id}/backups`;
    uploadName = `e2e-upload-${testInfo.project.name}-${Date.now().toString(36)}.dbs`;
  });

  test.afterAll(async () => {
    await api.deleteServersNamed(name);
    remoteFolder.restore();
  });

  test('a new application has no backups yet', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(backupsUrl);

    await expect(page.getByRole('tab', { name: t('tabBackups') })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('heading', { name: t('noBackupsYet') })).toBeVisible();
    await expect(page.getByRole('button', { name: t('backUpNow') })).toBeVisible();
    await journey.shot(page, 'backups-empty');
  });

  test('Back up now runs on the server and lists the file, verified', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(backupsUrl);

    const backUp = page.getByRole('button', { name: t('backUpNow') });
    await backUp.click();

    await expect(page.getByRole('status').filter({ hasText: t('backupRunning') })).toBeVisible();
    await expect(page.locator('button[aria-busy="true"]')).toBeDisabled();
    await journey.shot(page, 'backups-running');

    await expect(journey.toast(page, 'backupFinished')).toBeVisible({ timeout: 180_000 });
    await expect(backUp).toBeEnabled();
    const download = page.getByRole('link', { name: journey.matching('downloadNamed', '.+\\.dbs') }).first();
    await expect(download).toBeVisible();
    backupName = (await download.getAttribute('aria-label'))!.replace(journey.say('downloadNamed', { name: '' }), '');
    expect(backupName).toMatch(/\.dbs$/);
    const row = page.getByRole('row').filter({ hasText: backupName });
    await expect(journey.shown(row, t('verified'))).toBeVisible();
    // A one-off backup keeps no copy on the server once the manager's own copy is verified.
    if (remoteReachable) {
      await expect.poll(() => remoteExists(`${SSH.remoteBackupDir}/${backupName}`)).toBe(false);
    }
    await journey.shot(page, 'backups-taken');
  });

  test('the file downloads under its own name', async ({ page, journey }) => {
    await journey.signIn(page);
    await page.goto(backupsUrl);

    const link = page.getByRole('link', { name: journey.say('downloadNamed', { name: backupName }) });
    const [download] = await Promise.all([page.waitForEvent('download'), link.click()]);

    expect(download.suggestedFilename()).toBe(backupName);
    expect(statSync(await download.path()).size).toBeGreaterThan(0);
  });

  test('Verify runs a full check again and the row says Verified', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(backupsUrl);

    const verify = page.getByRole('button', { name: journey.say('verifyNamed', { name: backupName }) });
    await verify.click();
    await expect(verify).toBeDisabled();

    await expect(journey.toast(page, 'checkPassed')).toBeVisible({ timeout: 180_000 });
    await expect(journey.shown(page.getByRole('row').filter({ hasText: backupName }), t('verified'))).toBeVisible();
    await journey.shot(page, 'backups-verified');
  });

  test('a rehearsed restore runs the whole restore and changes nothing', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(backupsUrl);

    await page.getByRole('button', { name: journey.say('restoreNamed', { name: backupName }) }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('definition').filter({ hasText: backupName })).toBeVisible();
    await expect(dialog.getByRole('definition').filter({ hasText: name }).first()).toBeVisible();
    await journey.shot(page, 'backups-restore');
    await dialog.getByRole('button', { name: t('rehearse'), exact: true }).click();

    await expect(journey.toast(page, 'rehearsedRestore')).toBeVisible({ timeout: 180_000 });
  });

  test('Delete asks for the password first, then Undo brings the file back', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(backupsUrl);
    const link = page.getByRole('link', { name: journey.say('downloadNamed', { name: backupName }) });
    await expect(link).toBeVisible();

    await page.getByRole('button', { name: journey.say('deleteNamed', { name: backupName }) }).click();
    const prompt = page.getByRole('dialog');
    await expect(prompt).toContainText(backupName);
    await prompt.getByLabel(t('yourPassword'), { exact: true }).fill(ADMIN.password);
    await prompt.getByRole('button', { name: t('delete'), exact: true }).click();

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
    const row = page.getByRole('row').filter({ hasText: uploadName });
    await expect(journey.shown(row, t('uploaded'))).toBeVisible();
    await expect(page.getByRole('button', { name: journey.say('downloadNamed', { name: uploadName }) })).toBeVisible();
    await expect(page.getByRole('button', { name: journey.say('restoreNamed', { name: uploadName }) })).toHaveCount(0);
    await journey.shot(page, 'backups-uploaded');
  });

  test('an uploaded file downloads behind the password, decrypted', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(backupsUrl);

    await page.getByRole('button', { name: journey.say('downloadNamed', { name: uploadName }) }).click();
    const prompt = page.getByRole('dialog');
    await prompt.getByLabel(t('yourPassword'), { exact: true }).fill(ADMIN.password);
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      prompt.getByRole('button', { name: t('download'), exact: true }).click(),
    ]);

    expect(download.suggestedFilename()).toBe(uploadName);
    expect(statSync(await download.path()).size).toBe('not a backup, just bytes\n'.length);
  });

  test('an uploaded file is checked for being intact, never called a verified backup', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(backupsUrl);
    const row = page.getByRole('row').filter({ hasText: uploadName });
    await expect(journey.shown(row, t('sealedStored'))).toBeVisible();

    await page.getByRole('button', { name: journey.say('verifyNamed', { name: uploadName }) }).click();

    await expect(journey.toast(page, 'checkPassed')).toBeVisible({ timeout: 180_000 });
    await expect(journey.shown(row, t('sealedIntact'))).toBeVisible();
    await expect(journey.shown(row, t('verified'))).toHaveCount(0);
    await journey.shot(page, 'backups-upload-intact');
  });

  test('the Backups page lists the application with its files', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto('/backups');
    const main = page.getByRole('main');

    const row = main.getByRole('row').filter({ hasText: backupName });
    await expect(row.getByRole('link', { name, exact: true })).toBeVisible();
    await expect(row.getByRole('link', { name: journey.say('downloadNamed', { name: backupName }) })).toBeVisible();
    await expect(main.getByRole('row').filter({ hasText: uploadName })).toBeVisible();
    await main.getByRole('combobox', { name: t('filterApplication') }).click();
    // Each choice reads as the application on its server, both names isolated.
    await page.getByRole('option', { name: new RegExp(name) }).click();
    await expect(main.getByRole('row').filter({ hasText: /\.dbs/ })).toHaveCount(2);
    await journey.shot(page, 'all-backups');
  });
});
