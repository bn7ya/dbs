import { Api } from './support/api';
import { ADMIN, SSH } from './support/config';
import { baseUrlOf, expect, test } from './support/fixtures';

test.describe.configure({ mode: 'serial' });

test.describe('the console', () => {
  let api: Api;
  let name = '';
  let applicationId = '';
  let planName = '';

  test.beforeAll(async ({}, testInfo) => {
    api = await Api.signIn(baseUrlOf(testInfo));
    name = `e2e console ${testInfo.project.name} ${Date.now().toString(36)}`;
    planName = `${name} media`;
    applicationId = (await api.createServerWithApplication(name)).application.id;
    await api.capturePassphrase(applicationId);
  });

  test.afterAll(async () => {
    await api.deleteServersNamed(name);
  });

  test('app list prints every application, ours among them', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.getByRole('navigation', { name: /.+/ }).first().getByRole('link', { name: t('navConsole') }).click();

    await expect(page).toHaveURL(/\/console$/);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(t('consoleTitle'));
    const command = page.getByRole('textbox', { name: t('command') });
    await command.fill('app list');
    await command.press('Enter');

    const log = page.getByRole('log', { name: t('consoleLog') });
    await expect(log).toContainText('django_dbs app list');
    await expect(log).toContainText(name);
    await expect(log).toContainText(applicationId);
    await expect(log).toContainText(journey.say('consoleDone', { code: '0' }));
    await expect(command).toHaveValue('');
    await journey.shot(page, 'console-app-list');
  });

  test('a command that acts for real asks for the password, and runs with it', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto('/console');
    const command = page.getByRole('textbox', { name: t('command') });
    await command.fill(`plan add "${name}" "${planName}" --kind archive --path ${SSH.mediaDir} --manual`);
    await command.press('Enter');

    const prompt = page.getByRole('dialog', { name: t('consolePasswordTitle') });
    await expect(prompt).toContainText(planName);
    await prompt.getByLabel(t('yourPassword'), { exact: true }).fill('not-the-password');
    await prompt.getByRole('button', { name: t('consoleRunIt') }).click();
    await expect(prompt.getByText(t('wrongPassword'))).toBeVisible();
    await journey.shot(page, 'console-password');
    await prompt.getByLabel(t('yourPassword'), { exact: true }).fill(ADMIN.password);
    await prompt.getByRole('button', { name: t('consoleRunIt') }).click();

    await expect(prompt).toBeHidden();
    const log = page.getByRole('log', { name: t('consoleLog') });
    await expect(log).toContainText(`Added the plan ${planName}.`);
    expect((await api.plans(applicationId)).map((plan) => plan.name)).toContain(planName);
  });

  test('a backup the console starts is followed until it ends', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto('/console');
    const command = page.getByRole('textbox', { name: t('command') });
    await command.fill(`backup take "${name}"`);
    await command.press('Enter');

    const log = page.getByRole('log', { name: t('consoleLog') });
    const job = log.getByRole('listitem').filter({ hasText: journey.say('consoleJob', { id: '' }) }).last();
    await expect(job).toContainText(t('jobSucceeded'), { timeout: 180_000 });
    await expect(job.getByRole('link', { name: t('followActivity') })).toHaveAttribute('href', '/activity');
    await journey.shot(page, 'console-job');
    expect(await api.backups(applicationId)).toHaveLength(1);

    await command.press('ArrowUp');
    await expect(command).toHaveValue(`backup take "${name}"`);
  });
});
