import { Api } from './support/api';
import { ADMIN, SSH } from './support/config';
import { baseUrlOf, expect, test } from './support/fixtures';
import { acquireLock } from './support/lock';

test.describe.configure({ mode: 'serial' });

test.describe('the terminal', () => {
  let api: Api;
  let name = '';
  let serverId = '';
  let release: () => void = () => undefined;

  test.beforeAll(async ({}, testInfo) => {
    // An account may hold two terminals at a time; both projects open theirs one after the other.
    release = await acquireLock('terminal');
    api = await Api.signIn(baseUrlOf(testInfo));
    await api.closeTerminals();
    name = `e2e terminal ${testInfo.project.name} ${Date.now().toString(36)}`;
    serverId = (await api.createServer(name)).id;
  });

  test.afterAll(async () => {
    await api.closeTerminals();
    await api.deleteServersNamed(name);
    release();
  });

  test('a shell on the server answers what is typed, and closes', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(`/servers/${serverId}`);
    const tabs = page.getByRole('tablist', { name: t('serverSections') });
    await tabs.getByRole('tab', { name: t('tabServerTerminal') }).click();
    await expect(page).toHaveURL(new RegExp(`/servers/${serverId}/terminal$`));
    const main = page.getByRole('main');
    await expect(main).toContainText(SSH.username);

    await main.getByRole('button', { name: t('openTerminal') }).click();
    const prompt = page.getByRole('dialog');
    await prompt.getByLabel(t('yourPassword'), { exact: true }).fill(ADMIN.password);
    await prompt.getByRole('button', { name: t('openTheTerminal') }).click();
    await expect(prompt).toBeHidden();

    // The view's name isolates the server's name, so it is matched on the name alone.
    const shell = main.getByRole('group', { name: new RegExp(name) });
    await expect(main.getByRole('button', { name: t('closeTerminal') })).toBeVisible({ timeout: 60_000 });
    await expect(shell).toContainText('$', { timeout: 60_000 });
    await shell.getByRole('textbox').focus();
    await page.keyboard.type('echo $((6*7))');
    await page.keyboard.press('Enter');

    await expect(shell.getByRole('listitem').filter({ hasText: /^42\s*$/ })).toBeVisible({ timeout: 30_000 });
    await journey.shot(page, 'terminal');

    await main.getByRole('button', { name: t('closeTerminal') }).click();
    await expect(main.getByText(t('terminalClosed'))).toBeVisible({ timeout: 30_000 });
    await expect(main.getByRole('button', { name: t('openTerminal') })).toBeVisible();
    expect((await page.request.get('/api/terminals/')).ok()).toBe(true);
  });
});
