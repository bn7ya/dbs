import { Api } from './support/api';
import { ADMIN, TARGET } from './support/config';
import { baseUrlOf, expect, test } from './support/fixtures';

test.describe.configure({ mode: 'serial' });

test.describe('a developer deploys a change in place, then rehearses moving onto a second project', () => {
  // The fixture serves a second Django project unless E2E_SSH_TARGET_PROJECT_DIR is set empty.
  test.skip(TARGET.projectDir === '', 'needs a second Django project with django-dbs on the SSH fixture');

  let api: Api;
  let name = '';
  let applicationId = '';
  let targetName = '';

  test.beforeAll(async ({}, testInfo) => {
    test.setTimeout(240_000);
    api = await Api.signIn(baseUrlOf(testInfo));
    name = `e2e deploy ${testInfo.project.name} ${Date.now().toString(36)}`;
    targetName = `${name} target`;
    const { server, application } = await api.createServerWithApplication(name);
    applicationId = application.id;
    await api.createApplication(server.id, targetName, {
      project_dir: TARGET.projectDir,
      python_path: TARGET.python,
      remote_backup_dir: TARGET.remoteBackupDir,
      file_roots: [],
      env_path: `${TARGET.projectDir}/.env`,
    });
    await api.capturePassphrase(applicationId);
    expect((await api.takeBackup(applicationId)).status).toBe('succeeded');
  });

  test.afterAll(async () => {
    await api.deleteServersNamed(name);
  });

  test('deploy steps are chosen behind the password', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(`/applications/${applicationId}/deploy`);
    const deploy = page.getByRole('main').getByRole('region', { name: t('deployHere') });

    await deploy.getByRole('button', { name: t('chooseSteps') }).click();
    await deploy.getByRole('button', { name: t('addStep') }).click();
    await page.getByRole('menuitem', { name: t('stepMigrate') }).click();
    await deploy.getByRole('button', { name: t('saveSteps') }).click();

    const prompt = page.getByRole('dialog');
    await prompt.getByLabel(t('yourPassword'), { exact: true }).fill(ADMIN.password);
    await prompt.getByRole('button', { name: t('saveSteps') }).click();

    await expect(journey.toast(page, 'stepsSaved')).toBeVisible();
    await expect(deploy.getByRole('list', { name: t('deploySteps') }).getByRole('listitem')).toHaveCount(1);
    await expect(deploy.getByRole('list', { name: t('deploySteps') })).toContainText(t('stepMigrate'));
    expect((await api.application(applicationId)).deploy_steps).toHaveLength(1);
    await journey.shot(page, 'deploy-steps');
  });

  test('a rehearsed deploy runs every step and changes nothing', async ({ page, journey }) => {
    test.setTimeout(300_000);
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(`/applications/${applicationId}/deploy`);
    const deploy = page.getByRole('main').getByRole('region', { name: t('deployHere') });

    await deploy.getByRole('button', { name: t('deployRehearse'), exact: true }).click();

    await expect(deploy.getByText(t('deployRehearsed'))).toBeVisible({ timeout: 240_000 });
    const steps = deploy.getByRole('list').filter({ hasText: t('stepSafetyBackup') }).getByRole('listitem');
    for (const step of ['stepCheckApplication', 'stepSafetyBackup', 'stepMigrate'] as const) {
      await expect(steps.filter({ hasText: t(step) })).toContainText(t('stepDone'));
    }
    // Nothing changed, so there is nothing to check again.
    await expect(steps.filter({ hasText: t('stepFinalCheck') })).toContainText(t('stepSkipped'));
    await journey.shot(page, 'deploy-rehearsed');
  });

  test('a real deploy asks for the password and the application’s name', async ({ page, journey }) => {
    test.setTimeout(300_000);
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(`/applications/${applicationId}/deploy`);
    const deploy = page.getByRole('main').getByRole('region', { name: t('deployHere') });

    await deploy.getByLabel(t('yourPassword'), { exact: true }).fill(ADMIN.password);
    await deploy.getByRole('textbox', { name: t('deployConfirmName') }).fill(name);
    await deploy.getByRole('button', { name: t('deploy'), exact: true }).click();

    await expect(deploy.getByText(t('deployDone'))).toBeVisible({ timeout: 240_000 });
    const steps = deploy.getByRole('list').filter({ hasText: t('stepSafetyBackup') }).getByRole('listitem');
    for (const step of ['stepCheckApplication', 'stepSafetyBackup', 'stepMigrate', 'stepFinalCheck'] as const) {
      await expect(steps.filter({ hasText: t(step) })).toContainText(t('stepDone'));
    }
    await journey.shot(page, 'deploy-done');
  });

  test('a rehearsed move onto the other application runs every step and changes nothing', async ({
    page,
    journey,
  }) => {
    test.setTimeout(300_000);
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(`/applications/${applicationId}/deploy`);
    const move = page.getByRole('main').getByRole('region', { name: t('moveToAnother') });

    await move.getByRole('combobox', { name: t('moveTo') }).click();
    await page.getByRole('option', { name: new RegExp(targetName) }).click();
    await move.getByRole('button', { name: t('moveRehearse'), exact: true }).click();

    const steps = move.getByRole('list').filter({ hasText: t('moveStepRestore') }).getByRole('listitem');
    await expect(steps.filter({ hasText: t('moveStepCheck') })).toContainText(t('stepDone'), { timeout: 120_000 });
    await expect(move.getByText(t('moveRehearsed'))).toBeVisible({ timeout: 240_000 });
    await expect(steps.filter({ hasText: t('moveStepRestore') })).toContainText(t('stepDone'));
    await journey.shot(page, 'move-rehearsed');
  });
});
