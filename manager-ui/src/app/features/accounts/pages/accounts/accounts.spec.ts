import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { ApplicationRef } from '@angular/core';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatButtonHarness } from '@angular/material/button/testing';
import { MatDialogHarness } from '@angular/material/dialog/testing';
import { MatMenuHarness } from '@angular/material/menu/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthStore } from '@core/auth/state/auth.store';
import { MASTER } from '@core/auth/testing/identity.fixtures';
import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { AccountsStore } from '../../state/accounts.store';
import { NADIA, OMAR, SARA } from '../../testing/accounts.fixtures';
import { AccountsPage } from './accounts';

describe('AccountsPage', () => {
  let http: HttpTestingController;
  let fixture: ComponentFixture<AccountsPage>;

  const show = async (): Promise<HTMLElement> => {
    const restoring = TestBed.inject(AuthStore).restore();
    http.expectOne('/api/auth/me/').flush(MASTER);
    await restoring;
    fixture = TestBed.createComponent(AccountsPage);
    fixture.detectChanges();
    http.expectOne('/api/accounts/').flush([SARA, OMAR, NADIA]);
    await TestBed.inject(ApplicationRef).whenStable();
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  };

  const rows = (page: HTMLElement): string[][] =>
    Array.from(page.querySelectorAll('tr[mat-row]')).map((row) =>
      Array.from(row.querySelectorAll('td')).map((cell) => cell.textContent?.trim() ?? ''),
    );

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [
        AccountsStore,
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
      ],
    });
    TestBed.inject(LocaleStore).register({ en, ar });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('lists each account with its role, status, two-factor sign-in and password', async () => {
    const page = await show();

    const [sara, omar, nadia] = rows(page);
    expect(sara.slice(0, 3)).toEqual(['sara(you)', 'Master', 'Can sign in']);
    expect(omar.slice(1, 4)).toEqual(['Operator', 'Can sign in', 'On, 7 recovery codes left']);
    expect(omar[5]).toBe('Never');
    expect(nadia.slice(1, 5)).toEqual(['Viewer', 'Disabled', 'Set up at next sign-in', 'New one at next sign-in']);
  });

  it('offers no actions on the master account, and the right ones on the others', async () => {
    const page = await show();
    const loader = TestbedHarnessEnvironment.documentRootLoader(fixture);

    expect(page.querySelectorAll('tr[mat-row]')[0].querySelector('button')).toBeNull();
    (page.querySelectorAll('tr[mat-row]')[1].querySelector('button') as HTMLButtonElement).click();
    const menu = await loader.getHarness(MatMenuHarness);
    const items = await Promise.all((await menu.getItems()).map((item) => item.getText()));

    expect(items).toEqual([
      'Change the role',
      'Disable the account',
      'Reset two-factor sign-in',
      'Ask for a new password',
      'Make it the master account',
    ]);
  });

  it('disables an account once the master confirms', async () => {
    const page = await show();
    const loader = TestbedHarnessEnvironment.documentRootLoader(fixture);

    (page.querySelectorAll('tr[mat-row]')[1].querySelector('button') as HTMLButtonElement).click();
    const menu = await loader.getHarness(MatMenuHarness);
    await menu.clickItem({ text: 'Disable the account' });
    const confirm = await loader.getHarness(MatDialogHarness);
    expect(await (await confirm.host()).text()).toContain('cannot sign in until the account is enabled again');
    await (await confirm.getHarness(MatButtonHarness.with({ text: 'Disable' }))).click();

    const request = http.expectOne('/api/accounts/2/');
    expect(request.request.body).toEqual({ is_active: false });
    request.flush({ ...OMAR, is_active: false });
    await TestBed.inject(ApplicationRef).whenStable();
    fixture.detectChanges();

    expect(rows(page)[1][2]).toBe('Disabled');
  });

  it('adds an account through the form', async () => {
    await show();
    const loader = TestbedHarnessEnvironment.documentRootLoader(fixture);

    await (await loader.getHarness(MatButtonHarness.with({ text: 'Add an account' }))).click();
    const dialog = await loader.getHarness(MatDialogHarness);
    const host = await dialog.host();
    expect(await host.text()).toContain('Viewer');

    await (await dialog.getHarness(MatButtonHarness.with({ text: 'Add the account' }))).click();
    expect(await host.text()).toContain('Enter a username.');
    http.expectNone('/api/accounts/');
  });
});
