import type { Locator, Page } from '@playwright/test';
import { SSH } from './config';
import type { CopyKey } from './copy.types';
import { expect } from './fixtures';
import type { Journey } from './fixtures.types';

export const stepIs = async (scope: Page | Locator, name: string): Promise<void> => {
  await expect(scope.getByRole('button', { name: new RegExp(`^${name}`), expanded: true })).toBeVisible();
};

export const valueOf = (scope: Page | Locator, term: string): Locator =>
  scope.getByRole('term').filter({ hasText: term }).first().locator('xpath=following-sibling::*[1]');

export const fillAddress = async (form: Locator, { t }: Journey, name: string): Promise<void> => {
  await form.getByRole('textbox', { name: t('name'), exact: true }).fill(name);
  await form.getByRole('textbox', { name: t('host'), exact: true }).fill(SSH.host);
  await form.getByRole('spinbutton', { name: t('port') }).fill(String(SSH.port));
  await form.getByRole('textbox', { name: t('username') }).fill(SSH.username);
};

export const answer = async (scope: Locator, { t }: Journey, question: CopyKey, option: CopyKey): Promise<void> => {
  const choice = scope.getByRole('radiogroup', { name: t(question) }).getByRole('radio', { name: t(option), exact: true });
  await choice.check();
  await expect(choice).toBeChecked();
};
