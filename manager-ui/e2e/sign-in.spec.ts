import { expect, test } from '@playwright/test';

test('a signed-out visitor is sent to sign in', async ({ page }) => {
  await page.goto('/');

  await expect(page).toHaveURL(/\/sign-in/);
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
});

test('wrong credentials say so without saying which part was wrong', async ({ page }) => {
  await page.goto('/sign-in');

  await page.getByLabel(/username|اسم المستخدم/i).fill('nobody');
  // By role: the "Show password" button's label would match a label regex too.
  await page.getByRole('textbox', { name: /password|كلمة المرور/i }).fill('wrong-password');
  await page.getByRole('button', { name: /sign in|تسجيل الدخول/i }).click();

  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page).toHaveURL(/\/sign-in/);
});

test('the form reports each missing field', async ({ page }) => {
  await page.goto('/sign-in');

  await page.getByRole('button', { name: /sign in|تسجيل الدخول/i }).click();

  await expect(page.getByText(/enter your username|أدخل اسم المستخدم/i)).toBeVisible();
  await expect(page.getByText(/enter your password|أدخل كلمة المرور/i)).toBeVisible();
});

test('the page is reachable by keyboard alone', async ({ page }) => {
  await page.goto('/sign-in');

  await expect(page.getByLabel(/username|اسم المستخدم/i)).toBeVisible();

  // Nothing stands ahead of the form to skip: the skip link belongs to the signed-in shell
  // (`AppLayout`), so the first stop here is the username.
  await page.keyboard.press('Tab');
  await expect(page.getByLabel(/username|اسم المستخدم/i)).toBeFocused();
});

test('switching to Arabic flips the document direction', async ({ page }) => {
  await page.goto('/sign-in');

  // The switch is a segmented control: a listbox of two options, not two buttons.
  await page.getByRole('option', { name: 'العربية' }).click();

  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  await expect(page.locator('html')).toHaveAttribute('lang', 'ar');
});
