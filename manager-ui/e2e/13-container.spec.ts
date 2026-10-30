import { Api } from './support/api';
import { CONTAINER } from './support/config';
import { baseUrlOf, expect, test } from './support/fixtures';

test.describe.configure({ mode: 'serial' });

test.describe('an application in a Compose service', () => {
  test.skip(CONTAINER.engine === '', 'needs E2E_CONTAINER_ENGINE and the Compose project of scripts/e2e_fixture.sh');

  let api: Api;
  let name = '';
  let serverId = '';

  test.beforeAll(async ({}, testInfo) => {
    api = await Api.signIn(baseUrlOf(testInfo));
    name = `e2e compose ${testInfo.project.name} ${Date.now().toString(36)}`;
    serverId = (await api.createServer(name)).id;
  });

  test.afterAll(async () => {
    await api.deleteServersNamed(name);
  });

  test('discovery finds the service from its folder, and it backs up', async ({ page, journey }) => {
    test.setTimeout(420_000);
    const { t } = journey;
    const engine = t(CONTAINER.engine === 'podman' ? 'enginePodman' : 'engineDocker');
    await journey.signIn(page);
    await page.goto(`/servers/${serverId}/applications/new`);
    const form = page.getByRole('main');
    const next = form.getByRole('button', { name: t('next'), exact: true });

    await next.click();
    await form.getByRole('textbox', { name: t('folderOnServer') }).fill(CONTAINER.folder);
    await next.click();

    const service = form.getByRole('radio', { name: new RegExp(`^${journey.say('whereCompose', { engine })} web$`) });
    await expect(service).toBeChecked({ timeout: 180_000 });
    await expect(form.getByText(t('candidateRunning')).first()).toBeVisible();
    await journey.shot(page, 'compose-discovery');
    await next.click();

    await form.getByRole('textbox', { name: t('name'), exact: true }).fill(name);
    await form.getByRole('button', { name: t('addApplicationSubmit'), exact: true }).click();
    await journey.confirmPassword(page, 'continue');
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
    await expect(page.getByRole('main').getByText(journey.say('whereCompose', { engine })).first()).toBeVisible();
    const [application] = await api.applicationsOf(serverId);
    expect(application.kind).toBe('compose');
    expect(application.engine).toBe(CONTAINER.engine);
    expect(application.compose_service).toBe('web');
    expect(await api.backups(application.id)).toHaveLength(1);
    await journey.shot(page, 'compose-application');
  });
});
