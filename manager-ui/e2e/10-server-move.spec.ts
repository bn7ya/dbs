import { Api } from './support/api';
import { ADMIN, SSH } from './support/config';
import { baseUrlOf, expect, test } from './support/fixtures';
import { acquireLock } from './support/lock';
import { readRemote, remoteExists, remoteReachable, removeRemote } from './support/ssh-fs';

test.describe.configure({ mode: 'serial' });

test.describe('a developer moves a server onto another one, rehearsing it first', () => {
  let api: Api;
  let name = '';
  let sourceId = '';
  let targetId = '';
  let targetName = '';
  let folder = '';
  let applicationId = '';

  test.beforeAll(async ({}, testInfo) => {
    api = await Api.signIn(baseUrlOf(testInfo));
    const suffix = Date.now().toString(36);
    name = `e2e move ${testInfo.project.name} ${suffix}`;
    targetName = `${name} target`;
    const { server, application } = await api.createServerWithApplication(name);
    sourceId = server.id;
    applicationId = application.id;
    await api.capturePassphrase(application.id);
    // A second record of the same SSH account stands in for the new server.
    targetId = (await api.createServer(targetName)).id;
    folder = `${await api.homeOf(targetId)}/e2e-moved-${testInfo.project.name}-${suffix}`;
  });

  test.afterAll(async () => {
    await api.deleteServersNamed(name);
    removeRemote(folder);
  });

  test('the rehearsal plans every application, names what it installs, and changes nothing', async ({
    page,
    journey,
  }) => {
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
    if (remoteReachable) expect(remoteExists(folder)).toBe(false);
  });

  test('the real move installs, carries and restores the application, and the old one keeps running', async ({
    page,
    journey,
  }) => {
    test.skip(SSH.sudoPassword === '', 'E2E_SSH_SUDO_PASSWORD names the SSH account’s sudo password');
    test.setTimeout(900_000);
    // Both languages move the same project; one at a time keeps the package manager to one caller.
    const release = await acquireLock('server-move', 15 * 60_000);
    try {
      const { t, say } = journey;
      const movedName = `${name} (${targetName})`;
      await journey.signIn(page);
      await page.goto(`/servers/${sourceId}/move?target=${targetId}`);
      const move = page.getByRole('main');

      await move.getByRole('button', { name: t('next'), exact: true }).click();
      await move.getByRole('textbox', { name: t('moveNewFolder') }).fill(folder);
      await move.getByRole('button', { name: t('planTheMove'), exact: true }).click();
      await expect(move.getByText(t('moveSameMachine'))).toBeVisible({ timeout: 180_000 });
      await move.getByRole('button', { name: t('next'), exact: true }).click();

      // The plan found that this account's sudo asks for a password, so the move asks for it too.
      const sudo = move.getByLabel(say('moveSudo', { user: SSH.username, server: targetName }), { exact: true });
      await expect(sudo).toBeVisible();
      await sudo.fill(SSH.sudoPassword);
      await move.getByLabel(t('yourPassword'), { exact: true }).fill(ADMIN.password);
      await move.getByRole('textbox', { name: t('moveConfirmName') }).fill(targetName);
      await journey.shot(page, 'server-move-real');
      const started = page.waitForResponse(
        (response) => response.url().endsWith(`/api/servers/${sourceId}/move/`) && response.status() === 202,
      );
      await move.getByRole('button', { name: t('moveForReal'), exact: true }).click();
      const { activity } = (await (await started).json()) as { activity: number };

      await expect(move.getByText(t('movePrepare')).first()).toBeVisible({ timeout: 120_000 });
      const job = await api.finished(activity, 780_000);
      expect([job.status, job.error_code]).toEqual(['succeeded', '']);
      await expect(move.getByRole('heading', { name: t('movedApplications') })).toBeVisible({ timeout: 60_000 });
      await journey.shot(page, 'server-move-done');

      await move.getByRole('link', { name: movedName, exact: true }).click();
      await expect(page.getByRole('heading', { level: 1 })).toHaveText(movedName);
      const check = page.getByRole('main').getByRole('button', { name: t('checkNow') });
      await check.click();
      await expect(check).toBeEnabled({ timeout: 120_000 });
      await expect(page.getByRole('main').getByText(t('ready')).first()).toBeVisible();
      await journey.shot(page, 'server-move-moved-application');

      const [listed] = await api.applicationsOf(targetId);
      const moved = await api.application(listed.id);
      expect(moved.project_dir).toBe(folder);
      expect(moved.has_backup_passphrase).toBe(true);
      const restores = await api.activities(moved.id, 'relocation.restore');
      expect(restores.map((entry) => entry.status)).toEqual(['succeeded']);
      if (remoteReachable) {
        const env = readRemote(`${folder}/.env`)!.toString('utf8');
        expect(env).toContain(`${folder}/`);
        expect(env).not.toContain(`${SSH.projectDir}/`);
      }

      const [source] = await api.applicationsOf(sourceId);
      expect(source.id).toBe(applicationId);
      expect(source.project_dir).toBe(SSH.projectDir);
      expect((await api.backups(applicationId)).length).toBeGreaterThan(0);
    } finally {
      release();
    }
  });
});
