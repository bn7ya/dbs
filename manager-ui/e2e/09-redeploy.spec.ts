import { Api } from './support/api';
import { TARGET } from './support/config';
import { expect, test } from './support/fixtures';

test.describe.configure({ mode: 'serial' });

test.describe('moving to another server', () => {
  // The fixture serves one Django project unless E2E_SSH_TARGET_PROJECT_DIR names a second one.
  test.skip(TARGET.projectDir === '', 'needs a second Django project with django-dbs on the SSH fixture');

  let api: Api;
  let sourceId = '';
  let targetName = '';

  test.beforeAll(async ({}, testInfo) => {
    test.setTimeout(240_000);
    api = await Api.signIn(testInfo.project.use.baseURL ?? 'http://localhost:4200');
    const stamp = `${testInfo.project.name} ${Date.now().toString(36)}`;
    sourceId = (await api.createServer(`e2e move from ${stamp}`)).id;
    targetName = `e2e move to ${stamp}`;
    await api.createServer(targetName, {
      project_dir: TARGET.projectDir,
      python_path: TARGET.python || 'python3',
      remote_backup_dir: TARGET.remoteBackupDir,
      file_roots: [],
      env_path: '',
    });
    await api.capturePassphrase(sourceId);
    expect((await api.takeBackup(sourceId)).status).toBe('succeeded');
  });

  test.afterAll(async () => {
    for (const server of await api.findServers('e2e move ')) await api.deleteServer(server.id);
    await api.dispose();
  });

  test('a rehearsal runs every step and changes nothing', async ({ page, journey }) => {
    test.setTimeout(300_000);
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(`/servers/${sourceId}`);
    await page.getByRole('link', { name: t('moveToAnother') }).click();

    await expect(page).toHaveURL(new RegExp(`/servers/${sourceId}/move$`));
    await expect(page.getByRole('heading', { level: 2, name: t('moveToAnother') })).toBeVisible();
    await page.getByRole('combobox', { name: t('moveTo') }).click();
    await page.getByRole('option', { name: targetName }).click();
    await page.getByRole('button', { name: t('rehearse'), exact: true }).click();

    const steps = page.getByRole('main').getByRole('listitem');
    await expect(steps.filter({ hasText: t('stepCheckOther') })).toContainText(t('stepDone'), { timeout: 120_000 });
    await expect(page.getByText(t('rehearsed'))).toBeVisible({ timeout: 240_000 });
    await expect(steps.filter({ hasText: t('stepRestore') })).toContainText(t('stepDone'));
    await journey.shot(page, 'redeploy-rehearsed');
  });
});
