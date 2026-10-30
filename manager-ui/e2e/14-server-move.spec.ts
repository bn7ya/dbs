import { Api } from './support/api';
import { SSH } from './support/config';
import { baseUrlOf, expect, test } from './support/fixtures';

test.describe.configure({ mode: 'serial' });

test.describe('moving a server onto another one', () => {
  let api: Api;
  let name = '';
  let sourceId = '';
  let targetId = '';
  let targetName = '';
  let folder = '';

  test.beforeAll(async ({}, testInfo) => {
    api = await Api.signIn(baseUrlOf(testInfo));
    const suffix = Date.now().toString(36);
    name = `e2e move ${testInfo.project.name} ${suffix}`;
    targetName = `${name} target`;
    folder = `${SSH.projectDir}-moved-${testInfo.project.name}-${suffix}`;
    const { server, application } = await api.createServerWithApplication(name);
    sourceId = server.id;
    await api.capturePassphrase(application.id);
    // A second record of the same SSH account stands in for the new server; the plan only reads.
    targetId = (await api.createServer(targetName)).id;
  });

  test.afterAll(async () => {
    await api.deleteServersNamed(name);
  });

  test('a rehearsed move plans every application and changes nothing', async ({ page, journey }) => {
    test.setTimeout(240_000);
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(`/servers/${sourceId}`);
    await page.getByRole('main').getByRole('link', { name: t('serverMove') }).click();

    const move = page.getByRole('main');
    await expect(move.getByRole('heading', { name: t('serverMove'), level: 1 })).toBeVisible();
    await move.getByRole('radio', { name: new RegExp(targetName) }).check();
    await move.getByRole('button', { name: t('next'), exact: true }).click();

    await expect(move.getByRole('textbox', { name: t('moveNewName') })).toHaveValue(`${name} (${targetName})`);
    await move.getByRole('textbox', { name: t('moveNewFolder') }).fill(folder);
    await journey.shot(page, 'server-move-applications');
    await move.getByRole('button', { name: t('planTheMove'), exact: true }).click();

    await expect(move.getByText(t('moveSameMachine'))).toBeVisible({ timeout: 180_000 });
    await expect(move.getByText(t('moveInstalls'))).toBeVisible();
    await expect(move.getByText(t('moveBlocked'))).toHaveCount(0);
    await journey.shot(page, 'server-move-plan');

    await move.getByRole('button', { name: t('next'), exact: true }).click();
    await expect(move.getByRole('button', { name: t('moveForReal'), exact: true })).toBeVisible();
    // The plan's own Plan again can still be on screen while its step closes.
    await expect(move.getByRole('button', { name: t('movePlanAgain'), exact: true }).last()).toBeVisible();
    await journey.shot(page, 'server-move-confirm');

    expect(await api.applicationsOf(sourceId)).toHaveLength(1);
    expect(await api.applicationsOf(targetId)).toHaveLength(0);
  });
});
