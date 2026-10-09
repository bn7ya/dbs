import { readFileSync } from 'node:fs';
import { Api } from './support/api';
import { SSH } from './support/config';
import { expect, test } from './support/fixtures';
import { folderSnapshot, readRemote, remoteExists, remoteReachable, scratchFile } from './support/ssh-fs';

test.describe.configure({ mode: 'serial' });

test.describe('files', () => {
  const uploads = `${SSH.mediaDir}/uploads`;
  let api: Api;
  let serverId = '';
  let filesUrl = '';
  let uploadsFolder: ReturnType<typeof folderSnapshot>;
  let fileName = '';
  let folderName = '';

  test.beforeAll(async ({}, testInfo) => {
    api = await Api.signIn(testInfo.project.use.baseURL ?? 'http://localhost:4200');
    uploadsFolder = folderSnapshot(uploads);
    const server = await api.createServer(`e2e files ${testInfo.project.name} ${Date.now().toString(36)}`);
    serverId = server.id;
    filesUrl = `/servers/${serverId}/files`;
    const stamp = `${testInfo.project.name}-${Date.now().toString(36)}`;
    fileName = `e2e-${stamp}.txt`;
    folderName = `e2e-folder-${stamp}`;
  });

  test.afterAll(async () => {
    await api.deleteServer(serverId);
    await api.dispose();
    uploadsFolder.restore();
  });

  test('opens the first allowed folder and goes into uploads', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(filesUrl);

    await expect(page.getByRole('combobox', { name: t('allowedFolder') })).toContainText(SSH.mediaDir);
    await expect(page.getByRole('navigation', { name: t('folderPath') })).toContainText(SSH.mediaDir);
    await journey.shot(page, 'files-root');

    await page.getByRole('link', { name: journey.named('openFolder', 'uploads') }).click();

    await expect(page).toHaveURL(new RegExp(`${filesUrl}\\?path=${encodeURIComponent(uploads).replace(/%/g, '%')}`));
    await expect(page.getByRole('navigation', { name: t('folderPath') })).toContainText('uploads');
    await expect(page.getByRole('link', { name: journey.named('download', 'a.txt') })).toBeVisible();
    await expect(page.getByRole('link', { name: journey.named('download', 'b.bin') })).toBeVisible();
    await journey.shot(page, 'files-uploads');
  });

  test('downloads a.txt with the content it has on the server', async ({ page, journey }) => {
    await journey.signIn(page);
    await page.goto(`${filesUrl}?path=${encodeURIComponent(uploads)}`);

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('link', { name: journey.named('download', 'a.txt') }).click(),
    ]);

    expect(download.suggestedFilename()).toBe('a.txt');
    const content = readFileSync(await download.path());
    expect(content.length).toBeGreaterThan(0);
    if (remoteReachable) expect(content.equals(readRemote(`${uploads}/a.txt`)!)).toBe(true);
  });

  test('uploads a small file into the folder on screen', async ({ page, journey }, testInfo) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(`${filesUrl}?path=${encodeURIComponent(uploads)}`);
    const file = scratchFile(testInfo.outputDir, fileName, `hello from the ${journey.dir} journey\n`);

    const [chooser] = await Promise.all([
      page.waitForEvent('filechooser'),
      page.getByRole('button', { name: t('uploadFile') }).click(),
    ]);
    await chooser.setFiles(file);

    await expect(journey.toast(page, 'fileUploaded')).toBeVisible();
    await expect(page.getByRole('link', { name: journey.named('download', fileName) })).toBeVisible();
    if (remoteReachable) expect(remoteExists(`${uploads}/${fileName}`)).toBe(true);
  });

  test('creates a folder, refusing an empty name first', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(`${filesUrl}?path=${encodeURIComponent(uploads)}`);
    const opener = page.getByRole('button', { name: t('newFolder') });
    await opener.click();
    const dialog = page.getByRole('dialog');

    await dialog.getByRole('button', { name: t('createFolder') }).click();
    await expect(dialog.getByText(t('enterFolderName'))).toBeVisible();
    await expect(dialog.getByRole('textbox', { name: t('name'), exact: true })).toHaveAttribute('aria-invalid', 'true');

    // The dialog keeps focus inside it and hands it back on Escape.
    for (let i = 0; i < 6; i += 1) {
      await page.keyboard.press('Tab');
      expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);
    }
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    await expect(opener).toBeFocused();

    await opener.click();
    await dialog.getByRole('textbox', { name: t('name'), exact: true }).fill(folderName);
    await dialog.getByRole('button', { name: t('createFolder') }).click();

    await expect(journey.toast(page, 'folderCreated')).toBeVisible();
    await expect(page.getByRole('link', { name: journey.named('openFolder', folderName) })).toBeVisible();
    if (remoteReachable) expect(remoteExists(`${uploads}/${folderName}`)).toBe(true);
    await journey.shot(page, 'files-created');
  });

  test('deletes the folder and the file, asking first each time', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(`${filesUrl}?path=${encodeURIComponent(uploads)}`);

    await page.getByRole('button', { name: journey.named('delete', folderName) }).click();
    const confirmFolder = page.getByRole('alertdialog');
    await expect(confirmFolder.getByRole('heading', { level: 2 })).toHaveText(t('deleteThisFolder'));
    await expect(confirmFolder).toContainText(`${uploads}/${folderName}`);
    await journey.shot(page, 'files-delete-folder');
    await confirmFolder.getByRole('button', { name: t('delete'), exact: true }).click();

    await expect(journey.toast(page, 'folderDeleted')).toBeVisible();
    await expect(page.getByRole('link', { name: journey.named('openFolder', folderName) })).toHaveCount(0);

    await page.getByRole('button', { name: journey.named('delete', fileName) }).click();
    const confirmFile = page.getByRole('alertdialog');
    await expect(confirmFile.getByRole('heading', { level: 2 })).toHaveText(t('deleteThisFile'));
    await confirmFile.getByRole('button', { name: t('delete'), exact: true }).click();

    await expect(journey.toast(page, 'fileDeleted')).toBeVisible();
    await expect(page.getByRole('link', { name: journey.named('download', fileName) })).toHaveCount(0);
    if (remoteReachable) {
      expect(remoteExists(`${uploads}/${folderName}`)).toBe(false);
      expect(remoteExists(`${uploads}/${fileName}`)).toBe(false);
    }
  });

  test('a path outside the allowed folders is refused in words', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    const refused = page.waitForResponse((r) => r.url().includes('/api/files/') && r.url().includes('path=/etc'));
    await page.goto(`${filesUrl}?path=/etc`);

    expect((await refused).status()).toBe(403);
    await expect(page.getByRole('alert')).toHaveText(t('outsideAllowed'));
    await expect(page.getByRole('button', { name: t('tryAgain') })).toBeVisible();
    await expect(page.getByRole('button', { name: t('uploadFile') })).toBeDisabled();
    await expect(page.getByRole('button', { name: t('newFolder') })).toBeDisabled();
    await expect(page.getByRole('button', { name: t('signOut') }).first()).toBeVisible();
    await expect(page).toHaveURL(/path=(%2F|\/)etc/);
    await journey.shot(page, 'files-outside');
  });
});
