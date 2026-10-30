import { readFileSync } from 'node:fs';
import { Api } from './support/api';
import { ADMIN, SSH } from './support/config';
import { baseUrlOf, expect, test } from './support/fixtures';
import { acquireLock } from './support/lock';
import {
  appendRemote,
  folderSnapshot,
  readRemote,
  remoteExists,
  remoteReachable,
  scratchFile,
  writeRemote,
} from './support/ssh-fs';

test.describe.configure({ mode: 'serial' });

test.describe("a developer works with the application's media files on the server", () => {
  const uploads = `${SSH.mediaDir}/uploads`;
  let api: Api;
  let name = '';
  let filesUrl = '';
  let uploadsFolder: ReturnType<typeof folderSnapshot>;
  let fileName = '';
  let folderName = '';

  test.beforeAll(async ({}, testInfo) => {
    api = await Api.signIn(baseUrlOf(testInfo));
    uploadsFolder = folderSnapshot(uploads);
    name = `e2e files ${testInfo.project.name} ${Date.now().toString(36)}`;
    const { application } = await api.createServerWithApplication(name);
    filesUrl = `/applications/${application.id}/files`;
    const stamp = `${testInfo.project.name}-${Date.now().toString(36)}`;
    fileName = `e2e-${stamp}.txt`;
    folderName = `e2e-folder-${stamp}`;
  });

  test.afterAll(async () => {
    await api.deleteServersNamed(name);
    uploadsFolder.restore();
  });

  test('opens the first allowed folder and goes into uploads', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(filesUrl);

    await expect(page.getByRole('combobox', { name: t('allowedFolder') })).toContainText(SSH.mediaDir);
    await expect(page.getByRole('navigation', { name: t('folderPath') })).toContainText(SSH.mediaDir);
    await journey.shot(page, 'files-root');

    await page.getByRole('link', { name: journey.say('openFolder', { name: 'uploads' }) }).click();

    await expect(page).toHaveURL(new RegExp(`${filesUrl}\\?path=${encodeURIComponent(uploads).replace(/%/g, '%')}`));
    await expect(page.getByRole('navigation', { name: t('folderPath') })).toContainText('uploads');
    await expect(page.getByRole('button', { name: journey.say('fileDownloadNamed', { name: 'a.txt' }) })).toBeVisible();
    await expect(page.getByRole('button', { name: journey.say('fileDownloadNamed', { name: 'b.bin' }) })).toBeVisible();
    await journey.shot(page, 'files-uploads');
  });

  test('downloads a.txt with the content it has on the server', async ({ page, journey }) => {
    await journey.signIn(page);
    await page.goto(`${filesUrl}?path=${encodeURIComponent(uploads)}`);

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('button', { name: journey.say('fileDownloadNamed', { name: 'a.txt' }) }).click(),
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
    await expect(page.getByRole('button', { name: journey.say('fileDownloadNamed', { name: fileName }) })).toBeVisible();
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
    await expect(page.getByRole('link', { name: journey.say('openFolder', { name: folderName }) })).toBeVisible();
    if (remoteReachable) expect(remoteExists(`${uploads}/${folderName}`)).toBe(true);
    await journey.shot(page, 'files-created');
  });

  test('deletes the folder and the file, asking first each time', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(`${filesUrl}?path=${encodeURIComponent(uploads)}`);

    await page.getByRole('button', { name: journey.say('fileDeleteNamed', { name: folderName }) }).click();
    const confirmFolder = page.getByRole('alertdialog');
    await expect(confirmFolder.getByRole('heading', { level: 2 })).toHaveText(t('deleteThisFolder'));
    await expect(confirmFolder).toContainText(`${uploads}/${folderName}`);
    await journey.shot(page, 'files-delete-folder');
    await confirmFolder.getByRole('button', { name: t('delete'), exact: true }).click();

    await expect(journey.toast(page, 'folderDeleted')).toBeVisible();
    await expect(page.getByRole('link', { name: journey.say('openFolder', { name: folderName }) })).toHaveCount(0);

    await page.getByRole('button', { name: journey.say('fileDeleteNamed', { name: fileName }) }).click();
    const confirmFile = page.getByRole('alertdialog');
    await expect(confirmFile.getByRole('heading', { level: 2 })).toHaveText(t('deleteThisFile'));
    await confirmFile.getByRole('button', { name: t('delete'), exact: true }).click();

    await expect(journey.toast(page, 'fileDeleted')).toBeVisible();
    await expect(page.getByRole('button', { name: journey.say('fileDownloadNamed', { name: fileName }) })).toHaveCount(0);
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
    await expect(page.getByRole('banner').getByRole('button', { name: new RegExp(ADMIN.username) })).toBeVisible();
    await expect(page).toHaveURL(/path=(%2F|\/)etc/);
    await journey.shot(page, 'files-outside');
  });
});

test.describe("a developer keeps versions of the application's .env file and puts one back", () => {
  let api: Api;
  let name = '';
  let envUrl = '';
  let original: Buffer | null = null;
  let release: () => void = () => undefined;
  let addedKey = '';

  test.beforeAll(async ({}, testInfo) => {
    release = await acquireLock('envfile');
    api = await Api.signIn(baseUrlOf(testInfo));
    original = readRemote(SSH.envPath);
    name = `e2e env ${testInfo.project.name} ${Date.now().toString(36)}`;
    const { application } = await api.createServerWithApplication(name);
    envUrl = `/applications/${application.id}/environment`;
    addedKey = `E2E_${testInfo.project.name.toUpperCase()}_${Date.now().toString(36).toUpperCase()}`;
  });

  test.afterAll(async () => {
    if (original) writeRemote(SSH.envPath, original);
    await api.deleteServersNamed(name);
    release();
  });

  const keysOf = (content: Buffer | null): string[] =>
    (content?.toString('utf8') ?? '')
      .split('\n')
      .filter((line) => /^[A-Z_][A-Z0-9_]*=/.test(line))
      .map((line) => line.split('=')[0]);

  test('Pull now keeps the first version, key names shown and values masked', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(envUrl);

    await expect(page.getByRole('heading', { name: t('noVersionsYet') })).toBeVisible();
    await expect(page.getByRole('main')).toContainText(SSH.envPath);
    await journey.shot(page, 'env-empty');

    await page.getByRole('button', { name: t('pullNow') }).click();

    await expect(journey.toast(page, 'newVersionKept')).toBeVisible();
    await expect(page.getByRole('heading', { name: t('selectedVersion') })).toBeVisible();
    await expect(page.getByText(t('firstVersion'))).toBeVisible();
    const keys = keysOf(original);
    for (const key of keys.length ? keys : ['SECRET_KEY']) {
      await expect(page.getByRole('term').filter({ hasText: key })).toBeVisible();
    }
    const masked = page.getByRole('img', { name: t('valueHidden') });
    await expect(masked.first()).toBeVisible();
    if (keys.length) await expect(masked).toHaveCount(keys.length);
    await expect(page.getByRole('main')).not.toContainText('SECRET_KEY=');
    await journey.shot(page, 'env-pulled');
  });

  test('Show values asks for the password; Hide masks them again', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(envUrl);

    await page.getByRole('button', { name: t('showValues') }).click();
    const prompt = page.getByRole('dialog');
    await prompt.getByLabel(t('yourPassword'), { exact: true }).fill('not-the-password');
    await prompt.getByRole('button', { name: t('showValues') }).click();
    await expect(prompt.getByText(t('wrongPassword'))).toBeVisible();

    await prompt.getByLabel(t('yourPassword'), { exact: true }).fill(ADMIN.password);
    await prompt.getByRole('button', { name: t('showValues') }).click();

    await expect(prompt).toBeHidden();
    const content = page.getByRole('textbox', { name: t('fileContent') });
    await expect(content).toBeVisible();
    if (original) {
      expect((await content.inputValue()).replace(/\r\n/g, '\n')).toBe(original.toString('utf8'));
    } else {
      await expect(content).toHaveValue(/=/);
    }
    await journey.shot(page, 'env-revealed');

    await page.getByRole('button', { name: t('hideValues') }).click();

    await expect(content).toBeHidden();
    await expect(page.getByRole('img', { name: t('valueHidden') }).first()).toBeVisible();
  });

  test('pulling again with no change keeps nothing new', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(envUrl);
    const rows = page.getByRole('table').getByRole('button');
    await expect(rows).toHaveCount(1);

    await page.getByRole('button', { name: t('pullNow') }).click();

    await expect(journey.toast(page, 'noChange')).toBeVisible();
    await expect(rows).toHaveCount(1);
  });

  test('a change on the server pulls as a new version that compares with the previous', async ({ page, journey }) => {
    test.skip(!remoteReachable, 'E2E_SSH_FS is empty: the server file cannot be changed from here');
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(envUrl);
    appendRemote(SSH.envPath, `${addedKey}=1\n`);

    await page.getByRole('button', { name: t('pullNow') }).click();

    await expect(journey.toast(page, 'newVersionKept')).toBeVisible();
    await expect(page.getByRole('table').getByRole('button')).toHaveCount(2);
    await expect(page.getByRole('term').filter({ hasText: addedKey })).toBeVisible();

    await page.getByRole('button', { name: t('compare') }).click();

    await expect(page.getByRole('heading', { name: t('changesSince') })).toBeVisible();
    await expect(page.getByRole('term').filter({ hasText: t('addedKeys') })).toBeVisible();
    await expect(page.getByRole('listitem').filter({ hasText: addedKey })).toBeVisible();
    await journey.shot(page, 'env-compare');
  });

  test('pushing the earlier version back restores the file byte for byte', async ({ page, journey }) => {
    test.skip(!remoteReachable, 'E2E_SSH_FS is empty: the server file cannot be read from here');
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(envUrl);
    await page.getByRole('table').getByRole('button').nth(1).click();
    await expect(page.getByRole('term').filter({ hasText: addedKey })).toHaveCount(0);

    await page.getByRole('button', { name: t('pushThis') }).click();
    const confirm = page.getByRole('alertdialog');
    await expect(confirm.getByRole('heading', { level: 2 })).toHaveText(t('replaceEnv'));
    await expect(confirm).toContainText(SSH.envPath);
    await confirm.getByRole('button', { name: t('continue') }).click();

    const prompt = page.getByRole('dialog');
    await prompt.getByLabel(t('yourPassword'), { exact: true }).fill('not-the-password');
    await prompt.getByRole('button', { name: t('pushVersion') }).click();
    await expect(prompt.getByText(t('wrongPassword'))).toBeVisible();
    await journey.shot(page, 'env-push-wrong-password');
    await prompt.getByLabel(t('yourPassword'), { exact: true }).fill(ADMIN.password);
    await prompt.getByRole('button', { name: t('pushVersion') }).click();

    await expect(journey.toast(page, 'versionPushed')).toBeVisible();
    // The server's file already matched the newest version, so only the push adds a row.
    await expect(page.getByRole('table').getByRole('button')).toHaveCount(3);
    await expect(page.getByRole('table').getByRole('row').nth(1)).toContainText(t('pushed'));
    expect(readRemote(SSH.envPath)!.equals(original!)).toBe(true);
    await journey.shot(page, 'env-pushed');
  });
});
