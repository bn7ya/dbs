import { Api } from './support/api';
import { CONTAINER } from './support/config';
import { baseUrlOf, expect, test } from './support/fixtures';
import { answer, stepIs, valueOf } from './support/wizard';

test.describe.configure({ mode: 'serial' });

test.describe('a developer adds a project that runs in a Compose service, then backs it up and rehearses a restore', () => {
  test.skip(CONTAINER.engine === '', 'needs E2E_CONTAINER_ENGINE and the Compose project of scripts/e2e_fixture.sh');

  let api: Api;
  let name = '';
  let serverId = '';
  let applicationId = '';

  test.beforeAll(async ({}, testInfo) => {
    api = await Api.signIn(baseUrlOf(testInfo));
    name = `e2e compose ${testInfo.project.name} ${Date.now().toString(36)}`;
    serverId = (await api.createServer(name)).id;
  });

  test.afterAll(async () => {
    await api.deleteServersNamed(name);
  });

  test('the answers lead discovery to the running web service, which checks, keeps its passphrase and backs up', async ({
    page,
    journey,
  }) => {
    test.setTimeout(420_000);
    const { t, say } = journey;
    const engineKey = CONTAINER.engine === 'podman' ? 'enginePodman' : 'engineDocker';
    const engine = t(engineKey);
    await journey.signIn(page);
    await page.goto(`/servers/${serverId}/applications/new`);
    const form = page.getByRole('main');
    const next = form.getByRole('button', { name: t('next'), exact: true });

    await stepIs(form, t('stepProfile'));
    await answer(form, journey, 'qRunsIn', 'runsInCompose');
    await answer(form, journey, 'qEngine', engineKey);
    await answer(form, journey, 'qDatabase', 'databaseSqlite');
    await answer(form, journey, 'qDatabaseRuns', 'databaseInAFile');
    await answer(form, journey, 'qSettingsFrom', 'settingsComposeEnvFile');
    await expect(form.getByRole('radiogroup', { name: t('qProcessManager') })).toHaveCount(0);
    await journey.shot(page, 'compose-profile');
    await next.click();

    await stepIs(form, t('stepFolder'));
    await form.getByRole('textbox', { name: t('folderOnServer') }).fill(CONTAINER.folder);
    await next.click();

    await stepIs(form, t('stepDiscovery'));
    const service = form.getByRole('radio', { name: new RegExp(`^${say('whereCompose', { engine })} web$`) });
    await expect(service).toBeChecked({ timeout: 180_000 });
    await expect(journey.shown(form, t('candidateRunning')).first()).toBeVisible();
    await journey.shot(page, 'compose-discovery');
    await next.click();

    await stepIs(form, t('stepReview'));
    await form.getByRole('textbox', { name: t('name'), exact: true }).fill(name);
    await form.getByRole('button', { name: t('addApplicationSubmit'), exact: true }).click();
    await journey.confirmPassword(page, 'continue');
    await stepIs(form, t('stepCheck'));
    await expect(form.getByText(t('versionsWork'))).toBeVisible({ timeout: 180_000 });
    await journey.shot(page, 'compose-check');
    await next.click();
    await form.getByRole('button', { name: t('readPassphrase') }).click();
    await expect(form.getByText(t('passphraseSaved'))).toBeVisible({ timeout: 60_000 });
    await next.click();
    await form.getByRole('button', { name: t('takeTestBackup') }).click();
    await expect(form.getByText(t('testBackupWorked'))).toBeVisible({ timeout: 300_000 });
    await form.getByRole('link', { name: t('openApplication') }).click();

    await expect(page.getByRole('heading', { level: 1 })).toHaveText(name);
    const main = page.getByRole('main');
    await expect(main.getByText(say('whereCompose', { engine })).first()).toBeVisible();
    await expect(main.getByText(t('deploymentDiffers'))).toHaveCount(0);
    await expect(valueOf(main, t('qRunsIn'))).toContainText(t('runsInCompose'));
    const [application] = await api.applicationsOf(serverId);
    applicationId = application.id;
    expect(application.kind).toBe('compose');
    expect(application.engine).toBe(CONTAINER.engine);
    expect(application.compose_service).toBe('web');
    expect(await api.backups(application.id)).toHaveLength(1);
    await journey.shot(page, 'compose-application');
  });

  test('a rehearsed restore runs inside the service and changes nothing', async ({ page, journey }) => {
    test.setTimeout(300_000);
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(`/applications/${applicationId}/backups`);

    await page.getByRole('button', { name: journey.matching('restoreNamed', '.+\\.dbs') }).first().click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('definition').filter({ hasText: name }).first()).toBeVisible();
    await dialog.getByRole('button', { name: t('rehearse'), exact: true }).click();

    await expect(journey.toast(page, 'rehearsedRestore')).toBeVisible({ timeout: 240_000 });
    await journey.shot(page, 'compose-restore-rehearsed');
  });
});
