import { statSync } from 'node:fs';
import type { Locator, Page } from '@playwright/test';
import { Api } from './support/api';
import { ADMIN, SSH } from './support/config';
import { baseUrlOf, expect, test } from './support/fixtures';
import type { Journey } from './support/fixtures.types';
import { folderSnapshot } from './support/ssh-fs';

test.describe.configure({ mode: 'serial' });

const ZONE = 'Asia/Tokyo';
const ZONE_OFFSET = '+09:00';

const daysAhead = (days: number): { typed: string; iso: string } => {
  const day = new Date();
  day.setDate(day.getDate() + days);
  const month = String(day.getMonth() + 1).padStart(2, '0');
  const date = String(day.getDate()).padStart(2, '0');
  return { typed: `${month}/${date}/${day.getFullYear()}`, iso: `${day.getFullYear()}-${month}-${date}` };
};

const moment = async (scope: Locator, { t }: Journey, day: string, time: string): Promise<void> => {
  await scope.getByRole('textbox', { name: t('day'), exact: true }).fill(day);
  await scope.getByRole('combobox', { name: t('time'), exact: true }).fill(time);
  await scope.getByRole('combobox', { name: t('time'), exact: true }).blur();
};

type PlanAction = 'pause' | 'resume' | 'reschedule' | 'delete';

const planMenu = async (page: Page, journey: Journey, plan: string, item: PlanAction): Promise<void> => {
  await page.getByRole('button', { name: journey.say('planMore', { name: plan }) }).click();
  await page.getByRole('menuitem', { name: journey.t(item) }).click();
};

test.describe('a developer schedules backups in their time zone and collects dumps the server keeps', () => {
  let api: Api;
  let name = '';
  let applicationId = '';
  let scheduleUrl = '';
  let backupsUrl = '';
  let remoteFolder: ReturnType<typeof folderSnapshot>;
  const names = { dbs: '', archive: '', collect: '' };

  test.beforeAll(async ({}, testInfo) => {
    api = await Api.signIn(baseUrlOf(testInfo));
    remoteFolder = folderSnapshot(SSH.remoteBackupDir);
    name = `e2e plans ${testInfo.project.name} ${Date.now().toString(36)}`;
    const { application } = await api.createServerWithApplication(name);
    await api.capturePassphrase(application.id);
    applicationId = application.id;
    scheduleUrl = `/applications/${applicationId}/schedule`;
    backupsUrl = `/applications/${applicationId}/backups`;
    const stamp = Date.now().toString(36);
    names.dbs = `e2e daily ${stamp}`;
    names.archive = `e2e media ${stamp}`;
    names.collect = `e2e collect ${stamp}`;
  });

  test.afterAll(async () => {
    await api.deleteServersNamed(name);
    remoteFolder.restore();
  });

  test('the plan form refuses an empty name and a keep count of zero', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(scheduleUrl);
    await expect(page.getByRole('heading', { name: t('noPlansYet') })).toBeVisible();
    await page.getByRole('button', { name: t('createDbsPlan') }).click();
    const dialog = page.getByRole('dialog');
    const nameField = dialog.getByRole('textbox', { name: t('name'), exact: true });

    await expect(nameField).toHaveValue('django-dbs');
    await nameField.fill('');
    await dialog.getByRole('spinbutton', { name: t('keepHere') }).fill('0');
    await dialog.getByRole('button', { name: t('addPlanSubmit'), exact: true }).click();

    await expect(dialog.getByRole('textbox', { name: t('name'), exact: true })).toHaveAttribute('aria-invalid', 'true');
    await expect(dialog.getByRole('spinbutton', { name: t('keepHere') })).toHaveAttribute('aria-invalid', 'true');
    await expect(dialog).toBeVisible();
    await journey.shot(page, 'plan-form-validation');
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
  });

  test('a daily plan starts at its first run in its own time zone, and runs now', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(scheduleUrl);
    await page.getByRole('button', { name: t('createDbsPlan') }).click();
    const dialog = page.getByRole('dialog');
    const first = daysAhead(2);

    await expect(dialog.getByRole('combobox', { name: t('schedule') })).toContainText(t('daily'));
    await dialog.getByRole('textbox', { name: t('name'), exact: true }).fill(names.dbs);
    await moment(dialog.getByRole('group', { name: t('firstRun') }), journey, first.typed, '03:00');
    await dialog.getByRole('combobox', { name: t('timeZone') }).fill(ZONE);
    await page.getByRole('option', { name: ZONE, exact: true }).click();
    await expect(dialog.getByRole('combobox', { name: t('timeZone') })).toHaveValue(ZONE);
    await dialog.getByRole('spinbutton', { name: t('keepHere') }).fill('2');
    await journey.shot(page, 'plan-form');
    await dialog.getByRole('button', { name: t('addPlanSubmit'), exact: true }).click();

    await expect(journey.toast(page, 'planAdded')).toBeVisible();
    const row = page.getByRole('row').filter({ hasText: names.dbs });
    await expect(journey.shown(row, t('notRunYet'))).toBeVisible();
    await expect(journey.shown(row, t('planOn'))).toBeVisible();
    await expect(journey.shown(row, ZONE)).toBeVisible();
    await expect(row.getByText(journey.say('yourTime', { time: '' }))).toBeVisible();
    const [plan] = (await api.plans(applicationId)).filter((p) => p.name === names.dbs);
    expect(plan.time_zone).toBe(ZONE);
    expect(Date.parse(plan.next_run_at!)).toBe(Date.parse(`${first.iso}T03:00:00${ZONE_OFFSET}`));
    await journey.shot(page, 'plan-added');
    await journey.dismissToasts(page);

    const run = page.getByRole('button', { name: journey.say('runPlan', { name: names.dbs }) });
    await run.click();
    await expect(run).toBeDisabled();

    await expect(journey.toast(page, 'backupFinished')).toBeVisible({ timeout: 180_000 });
    await expect(journey.shown(row, t('succeeded'))).toBeVisible();
    await journey.shot(page, 'plan-ran');
  });

  test('a paused plan has no next run until it is resumed', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(scheduleUrl);
    const row = page.getByRole('row').filter({ hasText: names.dbs });

    await planMenu(page, journey, names.dbs, 'pause');
    await expect(journey.toast(page, 'paused')).toBeVisible();
    await expect(journey.shown(row, t('planPaused'))).toBeVisible();
    await expect(journey.shown(row, ZONE)).toHaveCount(0);
    expect((await api.plans(applicationId)).find((p) => p.name === names.dbs)?.enabled).toBe(false);
    await journey.shot(page, 'plan-paused');
    await journey.dismissToasts(page);

    await planMenu(page, journey, names.dbs, 'resume');
    await expect(journey.toast(page, 'resumed')).toBeVisible();
    await expect(journey.shown(row, t('planOn'))).toBeVisible();
    await expect(journey.shown(row, ZONE)).toBeVisible();
    const resumed = (await api.plans(applicationId)).find((p) => p.name === names.dbs)!;
    expect(resumed.enabled).toBe(true);
    expect(Date.parse(resumed.next_run_at!)).toBeGreaterThan(Date.now());
  });

  test('rescheduling moves the next run to the moment chosen in the plan’s zone', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(scheduleUrl);
    const next = daysAhead(5);

    await planMenu(page, journey, names.dbs, 'reschedule');
    const dialog = page.getByRole('dialog', { name: t('rescheduleTitle') });
    await moment(dialog, journey, next.typed, '04:30');
    await journey.shot(page, 'plan-reschedule');
    await dialog.getByRole('button', { name: t('reschedule'), exact: true }).click();

    await expect(dialog).toBeHidden();
    await expect(journey.toast(page, 'rescheduled')).toBeVisible();
    const moved = (await api.plans(applicationId)).find((p) => p.name === names.dbs)!;
    expect(Date.parse(moved.next_run_at!)).toBe(Date.parse(`${next.iso}T04:30:00${ZONE_OFFSET}`));
  });

  test('a folders plan archives the media folder and the archive downloads', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(scheduleUrl);
    await page.getByRole('button', { name: t('addPlan'), exact: true }).click();
    const dialog = page.getByRole('dialog');

    const kind = dialog.getByRole('radio', { name: t('kindFolders') });
    await kind.click();
    await expect(kind).toBeChecked();
    const folders = dialog.getByRole('textbox', { name: t('folders') });
    await folders.fill(SSH.mediaDir);
    await folders.press('Enter');
    await expect(dialog.getByRole('row').filter({ hasText: SSH.mediaDir })).toBeVisible();
    await dialog.getByRole('textbox', { name: t('name'), exact: true }).fill(names.archive);
    // What a folders plan reads is chosen behind the reader's own password.
    await dialog.getByLabel(t('yourPassword'), { exact: true }).fill(ADMIN.password);
    await dialog.getByRole('button', { name: t('addPlanSubmit'), exact: true }).click();

    await expect(journey.toast(page, 'planAdded')).toBeVisible();
    await journey.dismissToasts(page);
    await page.getByRole('button', { name: journey.say('runPlan', { name: names.archive }) }).click();
    await expect(journey.toast(page, 'backupFinished')).toBeVisible({ timeout: 180_000 });

    await page.goto(backupsUrl);
    const button = page.getByRole('button', { name: journey.matching('downloadNamed', '.+\\.tar\\.gz') });
    await expect(button).toBeVisible();
    await button.click();
    const prompt = page.getByRole('dialog');
    await prompt.getByLabel(t('yourPassword'), { exact: true }).fill(ADMIN.password);
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      prompt.getByRole('button', { name: t('download'), exact: true }).click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/\.tar\.gz$/);
    expect(statSync(await download.path()).size).toBeGreaterThan(0);
    await journey.shot(page, 'plan-archive');
  });

  test('an existing-files plan collects the .sql.gz files once, then nothing new', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(scheduleUrl);
    await page.getByRole('button', { name: t('addPlan'), exact: true }).click();
    const dialog = page.getByRole('dialog');

    const kind = dialog.getByRole('radio', { name: t('kindExisting') });
    await kind.click();
    await expect(kind).toBeChecked();
    await dialog.getByRole('textbox', { name: t('folder'), exact: true }).fill(SSH.existingDir);
    await dialog.getByRole('textbox', { name: t('pattern') }).fill('*.sql.gz');
    await dialog.getByRole('textbox', { name: t('name'), exact: true }).fill(names.collect);
    await dialog.getByLabel(t('yourPassword'), { exact: true }).fill(ADMIN.password);
    await journey.shot(page, 'plan-form-collect');
    await dialog.getByRole('button', { name: t('addPlanSubmit'), exact: true }).click();

    await expect(journey.toast(page, 'planAdded')).toBeVisible();
    await expect(journey.shown(page.getByRole('main'), `${SSH.existingDir}/*.sql.gz`)).toBeVisible();
    await journey.dismissToasts(page);
    const run = page.getByRole('button', { name: journey.say('runPlan', { name: names.collect }) });
    await run.click();

    const collected = journey.say('collected', { count: String(SSH.existingFiles.length) });
    await expect(page.getByText(collected, { exact: true }).first()).toBeVisible({ timeout: 180_000 });
    await journey.dismissToasts(page);
    await run.click();
    await expect(journey.toast(page, 'nothingNew')).toBeVisible({ timeout: 180_000 });

    await page.goto(backupsUrl);
    for (const file of SSH.existingFiles) {
      await expect(page.getByRole('button', { name: journey.say('downloadNamed', { name: file }) })).toBeVisible();
    }
    await expect(page.getByRole('button', { name: journey.matching('downloadNamed', '.+\\.sql\\.gz') })).toHaveCount(
      SSH.existingFiles.length,
    );
    await journey.shot(page, 'plan-collected');
  });

  test('deleting a plan keeps its backups listed', async ({ page, journey }) => {
    const { t } = journey;
    await journey.signIn(page);
    await page.goto(scheduleUrl);

    await planMenu(page, journey, names.archive, 'delete');
    const confirm = page.getByRole('alertdialog');
    await expect(confirm.getByRole('heading', { level: 2 })).toContainText(names.archive);
    await confirm.getByRole('button', { name: t('delete'), exact: true }).click();

    await expect(journey.toast(page, 'planDeleted')).toBeVisible();
    await expect(page.getByRole('button', { name: journey.say('runPlan', { name: names.archive }) })).toHaveCount(0);

    await page.goto(backupsUrl);
    await expect(page.getByRole('button', { name: journey.matching('downloadNamed', '.+\\.tar\\.gz') })).toHaveCount(1);
  });
});
